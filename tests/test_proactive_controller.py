# -*- coding: utf-8 -*-

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from connectors.calendar_intent import is_calendar_action
from connectors import telegram_bot_legacy as legacy
from engine import proactive_controller as pc
from engine import proactive_worker as pw
from engine.store import Store


TZ = ZoneInfo("Asia/Riyadh")


class ProactiveControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        self.base = dt.datetime(2026, 9, 11, 12, 0, tzinfo=TZ)
        pc.configure({"pilot_start": "2026-09-11", "pilot_days": 14}, store=self.store, now=self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_is_disabled_and_has_three_alert_budget(self):
        data = pc.status(self.store, self.base)
        self.assertFalse(data["enabled"])
        self.assertFalse(data["t3_approved"])
        self.assertEqual(data["max_alerts_per_day"], 3)
        self.assertEqual(data["quiet_hours"], "22:00-05:15")

    def test_reading_alert_uses_actual_event_baseline(self):
        pc.configure({"enabled": True}, store=self.store, now=self.base)
        sunday = dt.datetime(2026, 9, 13, 7, 0, tzinfo=TZ)
        alerts = pc.collect(now=sunday, store=self.store)
        self.assertTrue(any(a["kind"] == "reading" for a in alerts))

        pc.record_event("reading", detail="45 minutes", at=sunday, store=self.store)
        alerts_after_log = pc.collect(now=sunday, store=self.store)
        self.assertFalse(any(a["kind"] == "reading" for a in alerts_after_log))

    def test_exercise_never_guesses_missing_weekdays(self):
        pc.configure({"enabled": True}, store=self.store, now=self.base)
        sunday = dt.datetime(2026, 9, 13, 5, 30, tzinfo=TZ)
        self.assertFalse(any(a["kind"] == "exercise" for a in pc.collect(sunday, self.store)))

        pc.configure({"exercise_weekdays": [6]}, store=self.store, now=self.base)
        self.assertTrue(any(a["kind"] == "exercise" for a in pc.collect(sunday, self.store)))

    def test_quiet_hours_block_collection(self):
        pc.configure({"enabled": True, "exercise_weekdays": [6]}, store=self.store, now=self.base)
        quiet = dt.datetime(2026, 9, 13, 22, 30, tzinfo=TZ)
        self.assertEqual(pc.collect(quiet, self.store, include_context=True), [])

    def test_claim_alert_enforces_three_alert_budget(self):
        pc.configure({"max_alerts_per_day": 3}, store=self.store, now=self.base)
        alerts = [
            pc._alert(f"PA-{i}", "test", "reason", [], "one action")
            for i in range(4)
        ]
        self.assertEqual(
            [pc.claim_alert(alert, now=self.base, store=self.store) for alert in alerts],
            [True, True, True, False],
        )

    def test_response_is_local_update_and_has_controlled_values(self):
        alert = pc._alert("PA-RESP", "test", "reason", [], "one action")
        self.assertTrue(pc.claim_alert(alert, now=self.base, store=self.store))
        result = pc.record_response("PA-RESP", "تم", store=self.store)
        self.assertEqual(result["response"]["response"], "تم")
        with self.assertRaises(ValueError):
            pc.record_response("PA-RESP", "نفذ", store=self.store)

    def test_configuration_text_is_not_calendar_request(self):
        text = (
            "فعّل وضع Chief of Staff الاستباقي. سجّل كل تنبيه واستجابتي، "
            "واذكر موعد التسليم، ولا ترسل رسالة لطرف آخر."
        )
        self.assertFalse(is_calendar_action(text))
        self.assertFalse(is_calendar_action("سجّل كل التنبيهات في السجل واذكر موعد التسليم، دون إنشاء موعد."))
        self.assertTrue(is_calendar_action("ذكرني غدًا الساعة 5 مساءً بالتمرين"))
        self.assertTrue(is_calendar_action("سجّل موعد التسليم غدًا الساعة 5 مساءً"))

    def test_contextual_suggestion_cites_state_source(self):
        def seed(state):
            state["tasks"].append({"title": "مهمة متكررة", "status": "مفتوحة"})
            return True

        self.store.transaction(seed, "test_seed")
        alerts = pc.collect(now=self.base.replace(hour=12), store=self.store, include_context=True)
        self.assertTrue(alerts)
        self.assertEqual(alerts[0]["kind"], "contextual_suggestion")
        self.assertEqual(alerts[0]["evidence"][0]["source"], "StateStore.tasks")

    def test_blocker_and_learning_records_are_supported_sources(self):
        def seed(state):
            state["waiting_for"].append({"item": "اعتماد المورد", "status": "WAITING", "date": "2026-09-10"})
            state["knowledge_sources"].append({"source": "كتاب الإدارة", "status": "لم يبدأ", "date": "2026-09-09"})
            return True

        self.store.transaction(seed, "test_seed_sources")
        alerts = pc.collect(now=self.base, store=self.store, include_context=True)
        self.assertEqual(alerts[0]["kind"], "blocker")
        self.assertEqual(alerts[0]["evidence"][0]["date"], "2026-09-10")

    def test_telegram_proactive_command_is_a_control_plane(self):
        sent = []
        with patch.object(legacy, "send", side_effect=lambda _chat, text: sent.append(text)):
            legacy.command_proactive(7, "status")
        self.assertTrue(sent)
        self.assertIn("الطبقة الاستباقية", sent[-1])
        self.assertNotIn("معاينة موعد", sent[-1])

    def test_dry_run_has_no_external_or_local_side_effect(self):
        alert = pc._alert("PA-DRY", "test", "reason", [], "one action")
        with patch.object(pw, "_append_followup") as append, patch.object(pw.bot, "send") as send:
            result = pw.dispatch_alert(alert, dry_run=True, store=self.store)
        self.assertEqual(result, "dry_run")
        append.assert_not_called()
        send.assert_not_called()
        self.assertFalse(self.store.data["proactive_alerts"])

    def test_worker_requires_both_environment_and_state_enablement(self):
        with patch.dict(pw.os.environ, {"PROACTIVE_ENABLED": "1"}, clear=False):
            result = pw.run_once(dry_run=False, store=self.store, now=self.base)
        self.assertEqual(result["status"], "state_disabled_or_unapproved")
        self.assertEqual(result["candidates"], 0)

    def test_live_delivery_logs_proposed_then_sent_to_owner_only(self):
        pc.configure({"enabled": True, "t3_approved": True}, store=self.store, now=self.base)
        alert = pc._alert("PA-LIVE", "test", "reason", [], "one action")
        followup_events = []
        with patch.dict(pw.os.environ, {"TELEGRAM_ALLOWED_CHAT_ID": "123", "PROACTIVE_DRY_RUN": "0"}, clear=False), \
             patch.object(pw, "_append_followup", side_effect=lambda a, event, response="": followup_events.append((event, response))), \
             patch.object(pw.bot, "send") as send:
            result = pw.dispatch_alert(alert, dry_run=False, store=self.store)
        self.assertEqual(result, "sent")
        self.assertEqual([item[0] for item in followup_events], ["PROPOSED", "SENT"])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], 123)
        self.assertEqual(self.store.data["proactive_alerts"][0]["status"], "SENT")

    def test_external_context_redacts_row_contents(self):
        with patch.object(pw.sheet_intelligence, "snapshot", return_value={
            "Projects": [["2026-09-10", "OKR: unblock one outcome"]],
            "Private": [["2026-09-10", "patient diagnosis"]],
        }):
            evidence = pw._load_external_evidence()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["date"], "2026-09-10")
        self.assertNotIn("patient", evidence[0]["signal"].lower())
        self.assertNotIn("unblock one outcome", evidence[0]["signal"])


if __name__ == "__main__":
    unittest.main()

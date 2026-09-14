# -*- coding: utf-8 -*-
"""Offline regressions for Calendar rescheduling (إعادة الجدولة).

The agent has Google Calendar access, so reschedule language must route to a
deterministic preview -> approval -> delete-old + create-new flow instead of
falling through to a model that might claim it cannot reach the calendar.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from connectors import calendar_actions as calendar
from connectors import calendar_intent
from connectors import capability_truth as truth
from connectors import telegram_bot_legacy as legacy

TZ = ZoneInfo("Asia/Riyadh")


class RescheduleParsingTests(unittest.TestCase):
    def setUp(self):
        self.base = dt.datetime(2026, 8, 25, 10, 0, tzinfo=TZ)

    def test_arabic_full_reschedule(self):
        parsed = calendar.parse_reschedule_request(
            "أعد جدولة اجتماع العمير إلى غدًا الساعة 5:30 مساءً", self.base
        )
        self.assertEqual(parsed["search"], "اجتماع العمير")
        self.assertEqual(parsed["date"], dt.date(2026, 8, 26))
        self.assertEqual(parsed["time"], (17, 30))

    def test_change_appointment_verb(self):
        parsed = calendar.parse_reschedule_request(
            "غيّر الموعد اجتماع القسم إلى يوم الخميس الساعة 2 مساءً", self.base
        )
        self.assertEqual(parsed["search"], "اجتماع القسم")
        self.assertEqual(parsed["date"], dt.date(2026, 8, 27))
        self.assertEqual(parsed["time"], (14, 0))

    def test_postpone_verb_keeps_search_term(self):
        parsed = calendar.parse_reschedule_request("أجل موعد العمير إلى الأحد", self.base)
        self.assertEqual(parsed["search"], "العمير")
        self.assertEqual(parsed["date"], dt.date(2026, 8, 30))
        self.assertIsNone(parsed["time"])

    def test_english_reschedule(self):
        parsed = calendar.parse_reschedule_request(
            "reschedule team meeting to tomorrow 5pm", self.base
        )
        self.assertEqual(parsed["search"], "team meeting")
        self.assertEqual(parsed["date"], dt.date(2026, 8, 26))
        self.assertEqual(parsed["time"], (17, 0))

    def test_date_and_time_can_be_omitted(self):
        parsed = calendar.parse_reschedule_request("أعد جدولة اجتماع العمير", self.base)
        self.assertEqual(parsed["search"], "اجتماع العمير")
        self.assertIsNone(parsed["date"])
        self.assertIsNone(parsed["time"])

    def test_plain_yes_is_not_a_reschedule(self):
        self.assertFalse(calendar.is_reschedule_action("أجل، سأرسل التقرير لاحقًا"))
        self.assertFalse(calendar.is_reschedule_action("نعم أنا موافق"))


class RescheduleIntentTests(unittest.TestCase):
    def test_routes_reschedule_before_general_ai(self):
        text = "أعد جدولة اجتماع العمير إلى غدًا الساعة 5:30 مساءً"
        self.assertTrue(calendar_intent.is_reschedule_action(text))
        self.assertTrue(calendar_intent.routed_text(text).startswith("/reschedule "))

    def test_reminder_language_still_routes_to_remind(self):
        text = "ذكرني غدًا الساعة 5 مساءً بالتمرين"
        self.assertTrue(calendar_intent.is_calendar_action(text))
        self.assertFalse(calendar_intent.is_reschedule_action(text))
        self.assertTrue(calendar_intent.routed_text(text).startswith("/remind "))


class RescheduleCommandTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "id": "evt-123",
            "title": "اجتماع العمير",
            "start": "2026-08-25T09:00:00+03:00",
            "end": "2026-08-25T10:00:00+03:00",
            "link": "https://example/evt-123",
            "reminder_minutes": 60,
        }
        self.parsed = {
            "search": "العمير",
            "date": dt.date(2026, 8, 26),
            "time": (17, 30),
            "duration_minutes": None,
            "reminder_minutes": None,
        }

    def _run_reschedule(self, parsed, matches, request_text):
        legacy._PENDING_CALENDAR_RESCHEDULES.clear()
        try:
            with mock.patch.object(calendar, "parse_reschedule_request", return_value=parsed), \
                 mock.patch.object(calendar, "find_events", return_value=matches), \
                 mock.patch.object(legacy, "send") as send:
                legacy.command_reschedule(12345, request_text)
            return send, dict(legacy._PENDING_CALENDAR_RESCHEDULES)
        finally:
            legacy._PENDING_CALENDAR_RESCHEDULES.clear()

    def test_single_match_builds_preview(self):
        send, pending = self._run_reschedule(
            self.parsed, [self.event], "أعد جدولة اجتماع العمير إلى غدًا الساعة 5:30 مساءً"
        )
        self.assertEqual(len(pending), 1)
        item = next(iter(pending.values()))
        self.assertEqual(item["old_event_id"], "evt-123")
        self.assertEqual(item["proposal"]["title"], "اجتماع العمير")
        self.assertEqual(item["proposal"]["start"].hour, 17)
        self.assertEqual(item["proposal"]["start"].date(), dt.date(2026, 8, 26))
        self.assertIn("/confirm_reschedule", send.call_args.args[1])

    def test_no_match_asks_for_verification(self):
        send, pending = self._run_reschedule(
            self.parsed, [], "أعد جدولة اجتماع العمير إلى غدًا"
        )
        self.assertEqual(pending, {})
        self.assertIn("لم أجد", send.call_args.args[1])

    def test_multiple_matches_require_disambiguation(self):
        second = dict(self.event, id="evt-456", title="العمير — مراجعة ثانية")
        send, pending = self._run_reschedule(
            self.parsed, [self.event, second], "أعد جدولة موعد العمير إلى غدًا"
        )
        self.assertEqual(pending, {})
        self.assertIn("أكثر من موعد", send.call_args.args[1])

    def test_inherits_original_time_when_only_date_given(self):
        parsed = dict(self.parsed, time=None, date=dt.date(2026, 8, 26))
        _, pending = self._run_reschedule(parsed, [self.event], "أجل موعد العمير إلى غدًا")
        item = next(iter(pending.values()))
        self.assertEqual(item["proposal"]["start"].hour, 9)  # inherited 09:00
        self.assertEqual(item["proposal"]["start"].date(), dt.date(2026, 8, 26))


class ConfirmRescheduleCommandTests(unittest.TestCase):
    def tearDown(self):
        legacy._PENDING_CALENDAR_RESCHEDULES.clear()

    def test_valid_token_executes_reschedule(self):
        legacy._PENDING_CALENDAR_RESCHEDULES.clear()
        legacy._PENDING_CALENDAR_RESCHEDULES["tok"] = {
            "old_event_id": "evt-123",
            "proposal": {"title": "اجتماع العمير"},
            "chat_id": "12345",
            "expires": 9999999999,
        }
        receipt = {"id": "evt-new", "title": "اجتماع العمير", "start": "2026-08-26T17:30:00+03:00", "link": "https://example/new"}
        with mock.patch.object(calendar, "reschedule_event", return_value=receipt) as reschedule, \
             mock.patch.object(legacy, "send") as send:
            legacy.command_confirm_reschedule(12345, "tok")

        reschedule.assert_called_once_with("evt-123", {"title": "اجتماع العمير"})
        self.assertIn("إعادة جدولة", send.call_args.args[1])
        self.assertNotIn("tok", legacy._PENDING_CALENDAR_RESCHEDULES)

    def test_invalid_token_refuses(self):
        legacy._PENDING_CALENDAR_RESCHEDULES.clear()
        with mock.patch.object(calendar, "reschedule_event") as reschedule, \
             mock.patch.object(legacy, "send") as send:
            legacy.command_confirm_reschedule(12345, "bogus")

        reschedule.assert_not_called()
        self.assertIn("غير صالح", send.call_args.args[1])


class RescheduleEventTests(unittest.TestCase):
    def test_fails_closed_when_original_event_is_missing(self):
        with mock.patch.object(calendar, "_calendar_service") as service, \
             mock.patch.object(calendar, "create_event") as create, \
             mock.patch.object(calendar, "delete_event") as delete:
            service.return_value.events.return_value.get.return_value.execute.side_effect = RuntimeError("notFound")
            with self.assertRaisesRegex(RuntimeError, "لم يُنفَّذ"):
                calendar.reschedule_event("evt-missing", {"title": "x"})
        create.assert_not_called()
        delete.assert_not_called()

    def test_happy_path_creates_then_deletes(self):
        with mock.patch.object(calendar, "_calendar_service") as service, \
             mock.patch.object(calendar, "create_event", return_value={"id": "new", "title": "t", "start": "s", "link": "l"}) as create, \
             mock.patch.object(calendar, "delete_event", return_value={"id": "old", "deleted": True}) as delete:
            result = calendar.reschedule_event("old", {"title": "t"})
        create.assert_called_once_with({"title": "t"})
        delete.assert_called_once_with("old")
        self.assertEqual(result["id"], "new")
        self.assertEqual(result["old_id"], "old")


class CalendarDenialGuardTests(unittest.TestCase):
    def _live_snapshot(self):
        return truth.CapabilitySnapshot(
            sheet_configured=True,
            sheet_read_verified=True,
            sheet_write_route=True,
            sheet_tabs=("Projects",),
            calendar_tools_implemented=True,
            calendar_read_verified=True,
            calendar_write_route=True,
            telegram_configured=True,
        )

    def test_false_calendar_denial_is_replaced(self):
        request = "أعد جدولة اجتماع العمير إلى غدًا"
        bad = "لا أملك صلاحية الوصول المباشر لتقويمك (Google Calendar أو أي تقويم آخر) من هنا."
        with mock.patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertNotIn("لا أملك", corrected)
        self.assertIn("/reschedule", corrected)

    def test_english_calendar_denial_is_replaced(self):
        request = "reschedule the team meeting to tomorrow"
        bad = "I do not have direct access to your Google Calendar from here."
        with mock.patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertNotIn("do not have", corrected)
        self.assertIn("/reschedule", corrected)


if __name__ == "__main__":
    unittest.main()

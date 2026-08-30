import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.store import Store
from engine.multi_intent import NEEDS_INPUT, extract_intents, record_intents
from connectors import telegram_bot_legacy as legacy


class MultiIntentTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "state.json"
        store = Store(path=str(path))
        state = store.rows_all()
        state["unified_inbox"].append({
            "id": "IN-TEST",
            "source": "TELEGRAM",
            "source_ref": "telegram:1",
            "kind": "TEXT",
            "content": "seed",
            "status": "NEW",
            "classification": None,
        })
        store.commit(state, "test_seed")
        return store

    def test_one_message_extracts_decision_waiting_task_and_appointment(self):
        text = (
            "لازم أقرر هل نبدأ عيادة الدوخة أو نؤجلها. "
            "وأنتظر موافقة مدير المستشفى. "
            "ملف السياسة مطلوب قبل الخميس. "
            "والاثنين الساعة 9:30 عندي اجتماع."
        )
        kinds = [x.kind for x in extract_intents(text)]
        self.assertIn("DECISION", kinds)
        self.assertIn("WAITING_FOR", kinds)
        self.assertIn("TASK", kinds)
        self.assertIn("APPOINTMENT_CANDIDATE", kinds)

    def test_records_share_intake_and_relation_group_and_do_not_execute_calendar(self):
        store = self.make_store()
        text = (
            "لازم أقرر هل نبدأ الخدمة أو نؤجلها. "
            "وأنتظر موافقة الإدارة. "
            "إعداد ملف السياسة مطلوب. "
            "والاثنين الساعة 9:30 عندي اجتماع."
        )
        result = record_intents("IN-TEST", text, source_ref="telegram:1", store=store)
        state = store.reload().rows_all()
        self.assertGreaterEqual(result["record_count"], 4)
        linked = []
        for section in ("tasks", "waiting_for", "decisions", "action_queue"):
            linked.extend(row for row in state[section] if row.get("intake_id") == "IN-TEST")
        self.assertGreaterEqual(len(linked), 4)
        self.assertEqual({row["relation_group_id"] for row in linked}, {result["relation_group_id"]})
        appointment = next(row for row in linked if row.get("record_type") == "APPOINTMENT_CANDIDATE")
        self.assertEqual(appointment["status"], "NEEDS_CONFIRMATION")
        self.assertEqual(appointment["resolved_start"], NEEDS_INPUT)
        self.assertNotIn("start", appointment)

    def test_missing_execution_fields_are_needs_input(self):
        store = self.make_store()
        record_intents("IN-TEST", "إعداد سياسة التشغيل مطلوب", store=store)
        task = next(row for row in store.reload().rows_all()["tasks"] if row.get("intake_id") == "IN-TEST")
        self.assertEqual(task["owner"], NEEDS_INPUT)
        self.assertEqual(task["due_date"], NEEDS_INPUT)
        self.assertEqual(task["next_step"], NEEDS_INPUT)

    def test_explicit_approval_dependency_is_confirmed(self):
        store = self.make_store()
        text = (
            "لازم أقرر هل نبدأ الخدمة أو نؤجلها. "
            "وأنتظر موافقة مدير المستشفى، والافتتاح مشروط بالموافقة."
        )
        record_intents("IN-TEST", text, store=store)
        links = store.reload().rows_all().get("record_links", [])
        self.assertTrue(any(x.get("relation") == "BLOCKED_BY" and x.get("status") == "CONFIRMED" for x in links))

    def test_unproven_dependency_is_not_promoted_to_fact(self):
        store = self.make_store()
        text = "لازم أقرر هل نبدأ الخدمة أو نؤجلها. وأنتظر رد الإدارة على موضوع آخر."
        record_intents("IN-TEST", text, store=store)
        links = store.reload().rows_all().get("record_links", [])
        link = next(x for x in links if x.get("relation") == "POSSIBLE_DEPENDENCY")
        self.assertEqual(link["status"], NEEDS_INPUT)

    def test_repeated_recording_is_idempotent(self):
        store = self.make_store()
        text = "إعداد ملف السياسة مطلوب. والاثنين الساعة 9:30 عندي اجتماع."
        first = record_intents("IN-TEST", text, store=store)
        second = record_intents("IN-TEST", text, store=store)
        state = store.reload().rows_all()
        records = []
        for section in ("tasks", "waiting_for", "decisions", "action_queue"):
            records.extend(row for row in state[section] if row.get("intake_id") == "IN-TEST")
        self.assertEqual(len(records), first["record_count"])
        self.assertEqual(first["linked_record_ids"], second["linked_record_ids"])

    def test_clinical_input_is_minimized_and_not_written_to_general_records(self):
        store = self.make_store()
        result = record_intents("IN-TEST", "مريض رقم الملف 123 لديه ألم شديد", store=store)
        state = store.reload().rows_all()
        self.assertEqual(result["classifications"], ["CLINICAL_PRIVATE"])
        self.assertEqual(state["unified_inbox"][0]["content"], "[REDACTED_FROM_PERSONAL_OS]")
        self.assertFalse(any(row.get("intake_id") == "IN-TEST" for row in state["tasks"]))
        self.assertFalse(any(row.get("intake_id") == "IN-TEST" for row in state["decisions"]))

    def test_runtime_capture_calls_multi_intent_recorder(self):
        message = {"message_id": 77, "chat": {"id": 9, "type": "private"}}
        with patch("unified_inbox.add", return_value="IN-X") as add, patch(
            "unified_inbox.classify_and_record", return_value={"classifications": ["TASK"]}
        ) as classify:
            iid = legacy._local_capture("إعداد التقرير مطلوب", message, "TEXT")
        self.assertEqual(iid, "IN-X")
        add.assert_called_once()
        classify.assert_called_once()


if __name__ == "__main__":
    unittest.main()

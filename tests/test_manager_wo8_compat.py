import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.store import Store
from engine.multi_intent import record_intents
from engine import manager


class ManagerWO8CompatibilityTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(path=str(Path(tmp.name) / "state.json"))
        state = store.rows_all()
        state["unified_inbox"].append({
            "id": "IN-WO8",
            "source": "TELEGRAM",
            "source_ref": "telegram:88",
            "kind": "TEXT",
            "content": "seed",
            "status": "NEW",
        })
        store.commit(state, "seed")
        return store

    def test_fast_mutation_preserves_link_ids_and_skips_unknown_expected_date(self):
        store = self.make_store()
        record_intents(
            "IN-WO8",
            "لازم أقرر هل نبدأ الخدمة أو نؤجلها. وأنتظر موافقة الإدارة.",
            store=store,
        )
        state = store.reload().rows_all()
        waiting_before = next(row for row in state["waiting_for"] if row.get("intake_id") == "IN-WO8")
        rid = waiting_before["record_id"]
        group = waiting_before["relation_group_id"]

        changed, (summary, _events) = manager._mutate_fast(state)
        waiting_after = next(row for row in state["waiting_for"] if row.get("intake_id") == "IN-WO8")

        self.assertTrue(changed)  # legacy->schema v2 normalization only
        self.assertEqual(waiting_after["record_id"], rid)
        self.assertEqual(waiting_after["relation_group_id"], group)
        self.assertEqual(waiting_after["expected_by"], "NEEDS_INPUT")
        self.assertEqual(waiting_after["status"], "WAITING")
        self.assertEqual(summary["overdue"], 0)
        self.assertEqual(summary["actions"], 0)

    def test_fast_cycle_does_not_treat_needs_input_as_overdue(self):
        store = self.make_store()
        record_intents("IN-WO8", "وأنتظر موافقة الإدارة", store=store)
        with patch.object(manager, "Store", return_value=store), patch.object(manager, "log_event"):
            summary = manager.fast_cycle()
        self.assertEqual(summary["overdue"], 0)
        self.assertEqual(summary["actions"], 0)


if __name__ == "__main__":
    unittest.main()

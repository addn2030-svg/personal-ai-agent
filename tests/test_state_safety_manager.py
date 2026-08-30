import json
import tempfile
import threading
import unittest
from pathlib import Path

from engine.store import Store
from engine import manager


class StateSafetyManagerTests(unittest.TestCase):
    def test_parallel_increment_is_exact_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            store = Store(str(state_path))
            initial = store.rows_all()
            initial["test_counter"] = 0
            initial["tasks"].append({"id": "seed"})
            store.commit(initial, "seed")

            audit_path = Path(tmp) / "audit.jsonl"
            audit_path.write_text("", encoding="utf-8")

            n = 24
            errors = []

            def worker(i):
                try:
                    local = Store(str(state_path))

                    def mutate(data):
                        data["test_counter"] = int(data.get("test_counter", 0)) + 1
                        return True, i

                    local.transaction(mutate, "concurrency_test", worker=i)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            final = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final["test_counter"], n)
            audit_lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(audit_lines), n)
            self.assertEqual(final["meta"]["version"], n + 1)

    def test_manager_markers_persist_in_state_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            original_store = manager.Store
            try:
                manager.Store = lambda: Store(str(state_path))
                manager._update_markers(
                    hb_day="2026-08-30",
                    last_fast="2026-08-30T06:00:00+03:00",
                )
                reloaded = Store(str(state_path)).rows_all()
            finally:
                manager.Store = original_store

            self.assertEqual(reloaded["manager_markers"]["hb_day"], "2026-08-30")
            self.assertEqual(
                reloaded["manager_markers"]["last_fast"],
                "2026-08-30T06:00:00+03:00",
            )
            self.assertFalse((Path(tmp) / ".manager-markers.json").exists())


if __name__ == "__main__":
    unittest.main()

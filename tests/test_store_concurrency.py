import json
import tempfile
import threading
import unittest
from pathlib import Path

from engine.store import Store


class StoreConcurrencyTests(unittest.TestCase):
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
                except Exception as exc:  # pragma: no cover - reported below
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


if __name__ == "__main__":
    unittest.main()

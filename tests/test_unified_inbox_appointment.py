import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import unified_inbox
from engine.store import Store


class AppointmentInboxTests(unittest.TestCase):
    def test_appointment_requires_confirmation_in_state_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")

            def factory():
                return Store(state_path)

            with patch.object(unified_inbox, "Store", factory), patch.object(
                unified_inbox, "log_event", lambda *args, **kwargs: None
            ):
                iid = unified_inbox.add(
                    "TELEGRAM",
                    "موعد اجتماع غدًا الساعة 9",
                    source_ref="telegram:101",
                )
                status = unified_inbox.classify(iid, "APPOINTMENT")

            self.assertEqual(status, "NEEDS_CONFIRMATION")
            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            item = next(row for row in data["unified_inbox"] if row["id"] == iid)
            self.assertEqual(item["classification"], "APPOINTMENT")
            self.assertEqual(item["status"], "NEEDS_CONFIRMATION")
            self.assertEqual(item["next_action"], "Confirm appointment details")


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from connectors import brief_discovery as discovery
except ImportError:
    import brief_discovery as discovery


class BriefDiscoveryTests(unittest.TestCase):
    def test_extracts_priority_signals(self):
        data = {
            "Tasks": [
                ["Title", "Status", "Due", "Notes"],
                ["تحديث الجهاز", "غير مكتمل", "2026-08-28", "يحتاج قرار"],
                ["فرصة تحسين الحجز", "مفتوح", "", "معلومة مهمة"],
            ]
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            discovery, "SNAPSHOT_FILE", Path(tmp) / "snapshot.json"
        ):
            result = discovery.discover(data, today=dt.date(2026, 8, 24))
        self.assertEqual(result["stats"]["rows"], 2)
        self.assertEqual(len(result["upcoming_dates"]), 1)
        self.assertEqual(len(result["missing_or_incomplete"]), 1)
        self.assertEqual(len(result["decisions_required"]), 1)
        self.assertEqual(len(result["important_information"]), 1)

    def test_second_identical_snapshot_has_no_changes(self):
        data = {"Projects": [["Name"], ["مختبر القدم"]]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            discovery, "SNAPSHOT_FILE", Path(tmp) / "snapshot.json"
        ):
            first = discovery.discover(data)
            second = discovery.discover(data)
        self.assertEqual(first["stats"]["new_or_changed"], 1)
        self.assertEqual(second["stats"]["new_or_changed"], 0)


if __name__ == "__main__":
    unittest.main()

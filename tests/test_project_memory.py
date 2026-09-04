import unittest
from unittest.mock import patch

from connectors import project_memory


class ProjectMemoryTests(unittest.TestCase):
    def tearDown(self):
        project_memory._PENDING.clear()

    def test_prepare_requires_achievement(self):
        with self.assertRaises(ValueError):
            project_memory.prepare("")

    def test_prepare_rejects_secrets(self):
        with self.assertRaises(ValueError):
            project_memory.prepare("API key = abc || next")

    def test_prepare_returns_confirm_command(self):
        digest, preview = project_memory.prepare("أنشأت الملفات || اختبر القراءة")
        self.assertEqual(len(digest), 10)
        self.assertIn("/confirm_memory " + digest, preview)
        self.assertIn("أنشأت الملفات", preview)

    def test_confirm_updates_decision_only_when_present(self):
        digest, _ = project_memory.prepare("تم الربط || الاختبار || اعتماد الذاكرة")
        with patch.object(project_memory, "_append") as append:
            result = project_memory.confirm(digest)
        self.assertEqual(append.call_count, 3)
        self.assertIn("Decision.md", result)

    def test_confirm_without_decision_updates_two_docs(self):
        digest, _ = project_memory.prepare("تم الربط || الاختبار")
        with patch.object(project_memory, "_append") as append:
            result = project_memory.confirm(digest)
        self.assertEqual(append.call_count, 2)
        self.assertNotIn("Decision.md", result)


if __name__ == "__main__":
    unittest.main()

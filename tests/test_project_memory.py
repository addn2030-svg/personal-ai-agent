# -*- coding: utf-8 -*-
import unittest
from unittest import mock

from connectors import project_memory


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self):
        project_memory._PENDING.clear()

    def tearDown(self):
        project_memory._PENDING.clear()

    def test_prepare_requires_explicit_confirm(self):
        token, preview = project_memory.prepare("تم إصلاح الجدولة || اختبار الذاكرة")
        self.assertEqual(len(token), 10)
        self.assertIn(token, project_memory._PENDING)
        self.assertIn("/confirm_memory", preview)
        self.assertIn("تم إصلاح الجدولة", preview)

    def test_prepare_rejects_secrets_and_patient_identifiers(self):
        for text in (
            "api key ABC || next",
            "token secret || next",
            "اسم المريض أحمد || next",
            "MRN 123 || next",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    project_memory.prepare(text)

    def test_confirm_writes_status_progress_and_optional_decision(self):
        token, _ = project_memory.prepare("إنجاز || خطوة || قرار")
        calls = []

        def fake_append(document_id, marker, value):
            calls.append((document_id, marker, value))
            return True

        with mock.patch.object(project_memory, "_append_once", side_effect=fake_append):
            result = project_memory.confirm(token)

        self.assertIn("Progress.md", result)
        self.assertIn("Status.md", result)
        self.assertIn("Decision.md", result)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(f"[memory:{token}]" in value for _, _, value in calls))
        self.assertNotIn(token, project_memory._PENDING)

    def test_confirm_without_decision_writes_two_docs(self):
        token, _ = project_memory.prepare("إنجاز || خطوة")
        with mock.patch.object(project_memory, "_append_once", return_value=True) as append:
            result = project_memory.confirm(token)
        self.assertIn("Progress.md", result)
        self.assertIn("Status.md", result)
        self.assertNotIn("Decision.md", result)
        self.assertEqual(append.call_count, 2)

    def test_failed_write_keeps_token_for_safe_retry(self):
        token, _ = project_memory.prepare("إنجاز || خطوة")
        with mock.patch.object(project_memory, "_append_once", side_effect=RuntimeError("drive down")):
            with self.assertRaises(RuntimeError):
                project_memory.confirm(token)
        self.assertIn(token, project_memory._PENDING)

    def test_read_memory_is_bounded_and_labelled(self):
        docs = {
            "status": {"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "STATUS"}}]}}]}},
            "progress": {"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "PROGRESS"}}]}}]}},
            "decision": {"body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "DECISION"}}]}}]}},
        }
        with mock.patch.object(project_memory, "_document", side_effect=lambda key: docs[key]):
            text = project_memory.read_memory(max_chars=500)
        self.assertIn("الحالة الحالية", text)
        self.assertIn("STATUS", text)
        self.assertIn("PROGRESS", text)
        self.assertIn("DECISION", text)
        self.assertLessEqual(len(text), 500)


if __name__ == "__main__":
    unittest.main()

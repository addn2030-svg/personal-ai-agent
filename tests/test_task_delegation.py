import unittest
from unittest.mock import Mock, patch

from connectors import task_delegation as team


class TaskDelegationTests(unittest.TestCase):
    def test_auto_routes_research_to_gemini(self):
        self.assertEqual(team.choose_agent("ابحث في Instagram عن اتجاهات العلاج الطبيعي"), "gemini")

    def test_auto_routes_verification_to_gpt(self):
        self.assertEqual(team.choose_agent("راجع هذا العقد وحدد المخاطر"), "gpt")

    def test_auto_routes_management_to_claude(self):
        self.assertEqual(team.choose_agent("رتب أولويات المشروع لهذا الأسبوع"), "claude")

    def test_parse_named_agent(self):
        agent, task = team.parse_delegate("gpt راجع هذه الخطة")
        self.assertEqual(agent, "gpt")
        self.assertEqual(task, "راجع هذه الخطة")

    def test_private_identifiers_do_not_go_to_external_gpt(self):
        fallback = Mock()
        with self.assertRaisesRegex(ValueError, "بيانات خاصة"):
            team.delegate(1, "gpt راجع حالة المريض رقم الملف 12345", bedrock_fallback=fallback)
        fallback.assert_not_called()

    def test_auto_private_task_goes_to_bedrock(self):
        fallback = Mock(return_value=("protected", {}, 3, []))
        result = team.delegate(1, "راجع حالة المريض رقم الملف 12345", bedrock_fallback=fallback)
        self.assertEqual(result.provider, "bedrock")
        self.assertEqual(result.answer, "protected")
        fallback.assert_called_once()

    def test_auto_openrouter_failure_falls_back_to_bedrock(self):
        fallback = Mock(return_value=("fallback", {}, 4, []))
        with patch.object(team, "_openrouter_agent", side_effect=RuntimeError("HTTP 402")):
            result = team.delegate(1, "ابحث عن اتجاهات عامة", bedrock_fallback=fallback)
        self.assertEqual(result.provider, "bedrock")
        self.assertTrue(result.fallback)

    def test_named_gemini_failure_does_not_impersonate_with_bedrock(self):
        fallback = Mock(return_value=("fallback", {}, 4, []))
        with patch.object(team, "_openrouter_agent", side_effect=RuntimeError("HTTP 402")):
            with self.assertRaisesRegex(RuntimeError, "HTTP 402"):
                team.delegate(1, "gemini ابحث عن اتجاهات عامة", bedrock_fallback=fallback)
        fallback.assert_not_called()

    def test_council_rejects_private_identifiers(self):
        with self.assertRaisesRegex(ValueError, "بيانات مريض"):
            team.council(1, "ناقش حالة اسم المريض أحمد رقم الملف 123")


if __name__ == "__main__":
    unittest.main()

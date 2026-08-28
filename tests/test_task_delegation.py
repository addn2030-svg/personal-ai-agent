import json
import unittest
from unittest.mock import Mock, patch

from connectors import task_delegation as team
from connectors import team_orchestrator as v08


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

    def test_active_mission_requires_objective(self):
        with self.assertRaisesRegex(ValueError, "اكتب الهدف"):
            team.mission(1, "")

    def test_active_mission_rejects_private_identifiers_before_agents(self):
        with self.assertRaisesRegex(ValueError, "معرّفات خاصة"):
            team.mission(1, "حل مشكلة للمريض رقم الملف 554433")

    def test_v08_handoff_regression_gemini_then_gpt_then_claude(self):
        calls = []

        def fake(agent, task, **kwargs):
            calls.append((agent, task, kwargs))
            if agent == "claude" and "MISSION PLANNER" in task:
                plan = {
                    "mission_summary": "Improve reliability",
                    "gemini_task": "Explore integration alternatives",
                    "gpt_task": "Audit reliability risks",
                    "success_criteria": ["stable", "safe"],
                    "manager_focus": "Choose the safest practical sequence",
                }
                return team.AgentResult("claude", "claude", "openrouter", "claude", json.dumps(plan))
            if agent == "gemini":
                return team.AgentResult("gemini", "gemini", "gemini", "gemini", "Gemini findings")
            if agent == "gpt":
                self.assertIn("Gemini findings", task)
                self.assertIn("GEMINI HANDOFF", task)
                return team.AgentResult("gpt", "gpt", "openai", "gpt", "GPT risks")
            if agent == "claude" and "MISSION SYNTHESIS" in task:
                self.assertIn("Gemini findings", task)
                self.assertIn("GPT risks", task)
                return team.AgentResult("claude", "claude", "openrouter", "claude", "Unified manager decision")
            raise AssertionError("unexpected call")

        with patch.object(v08, "routed_agent", side_effect=fake):
            result = v08.mission(1, "Improve agent reliability")

        self.assertIn("🎯 AI Mission v0.8", result)
        self.assertIn("Handoff Gemini→GPT: ✅", result)
        self.assertIn("Unified manager decision", result)
        order = [a for a, _t, _k in calls]
        self.assertLess(order.index("gemini"), order.index("gpt"))

    def test_v08_handoff_regression_continues_if_gemini_fails(self):
        def fake(agent, task, **kwargs):
            if agent == "claude" and "MISSION PLANNER" in task:
                return team.AgentResult(
                    "claude", "claude", "openrouter", "claude",
                    json.dumps({
                        "mission_summary": "x",
                        "gemini_task": "research x",
                        "gpt_task": "audit x",
                        "success_criteria": ["done"],
                        "manager_focus": "finish",
                    }),
                )
            if agent == "gemini":
                raise RuntimeError("temporary provider error")
            if agent == "gpt":
                self.assertIn("GEMINI HANDOFF — unavailable", task)
                return team.AgentResult("gpt", "gpt", "openai", "gpt", "risk review")
            if agent == "claude" and "MISSION SYNTHESIS" in task:
                return team.AgentResult("claude", "claude", "openrouter", "claude", "manager result")
            raise AssertionError("unexpected")

        with patch.object(v08, "routed_agent", side_effect=fake):
            result = v08.mission(1, "Improve x")

        self.assertIn("Unavailable specialist", result)
        self.assertIn("Handoff Gemini→GPT: ⚠️ partial", result)
        self.assertIn("manager result", result)


if __name__ == "__main__":
    unittest.main()

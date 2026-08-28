import unittest
from unittest.mock import patch

from connectors import lean_missions
from connectors import model_gateway as models
from connectors import task_delegation as base
from connectors import team_orchestrator as team


class TeamOrchestratorTests(unittest.TestCase):
    def test_bounded_text_marks_truncation(self):
        text = "A" * 1000
        bounded = team._bounded_text(text, limit=400)
        self.assertIn("HANDOFF_TRUNCATED", bounded)
        self.assertLessEqual(len(bounded), 400)

    def test_routed_agent_reports_actual_provider(self):
        with patch.object(
            models, "openrouter_chat", return_value=("answer", {}, 5)
        ), patch.object(
            models, "last_route", return_value={"provider": "openai", "model": "gpt-5.6-sol", "fallback": False}
        ):
            result = team.routed_agent("gpt", "review")
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.model, "gpt-5.6-sol")
        self.assertEqual(result.answer, "answer")

    def test_v08_install_does_not_override_active_v09_surface(self):
        lean_missions.install()
        team.install()
        self.assertIs(base.mission, lean_missions.mission)
        self.assertIs(base.agents_status_text, lean_missions.agents_status_text)
        self.assertTrue(callable(team.mission))


if __name__ == "__main__":
    unittest.main()

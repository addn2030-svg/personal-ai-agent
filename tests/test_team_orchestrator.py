import unittest
from unittest.mock import patch

from connectors import model_gateway as models
from connectors import task_delegation as base
from connectors import team_orchestrator as team


class TeamOrchestratorTests(unittest.TestCase):
    def test_bounded_text_marks_truncation(self):
        text = "A" * 200
        bounded = team._bounded_text(text, limit=100)
        self.assertIn("HANDOFF_TRUNCATED", bounded)
        self.assertLessEqual(len(bounded), 110)

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

    def test_install_exposes_v08_mission_on_legacy_module(self):
        team.install()
        self.assertIs(base.mission, team.mission)
        self.assertIs(base.agents_status_text, team.agents_status_text)


if __name__ == "__main__":
    unittest.main()

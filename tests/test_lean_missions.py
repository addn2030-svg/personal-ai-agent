import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from connectors import bedrock_team
from connectors import lean_missions as lean
from connectors import team_orchestrator as v08


def br(text, model="model", in_tokens=10, out_tokens=5):
    return bedrock_team.BedrockTeamResult(
        text=text,
        model=model,
        usage={"inputTokens": in_tokens, "outputTokens": out_tokens},
        latency_ms=1,
    )


class LeanMissionTests(unittest.TestCase):
    def test_default_simple_mission_uses_manager_only(self):
        with patch.object(lean.bedrock_team, "manager", return_value=br("DECISION")) as manager, patch.object(
            lean.bedrock_team, "lean_specialist"
        ) as specialist:
            result = lean.mission(1, "Give me three priorities for tomorrow")

        self.assertIn("AI Mission v0.9 — LEAN", result)
        self.assertIn("Calls: 1", result)
        self.assertIn("DECISION", result)
        manager.assert_called_once()
        specialist.assert_not_called()

    def test_complex_lean_uses_one_specialist_then_manager(self):
        with patch.object(
            lean.bedrock_team, "lean_specialist", return_value=br("SPECIALIST", "luna")
        ) as specialist, patch.object(
            lean.bedrock_team, "manager", return_value=br("DECISION", "claude")
        ) as manager, patch.object(lean.bedrock_team, "critic") as critic:
            result = lean.mission(1, "Improve rehabilitation workflow and propose a plan")

        self.assertIn("Calls: 2", result)
        self.assertIn("specialist=bedrock:luna", result)
        specialist.assert_called_once()
        manager.assert_called_once()
        critic.assert_not_called()

    def test_standard_risk_adds_critic_only_when_needed(self):
        with patch.object(
            lean.bedrock_team, "lean_specialist", return_value=br("SPECIALIST", "luna")
        ), patch.object(
            lean.bedrock_team, "critic", return_value=br("CRITIC", "luna")
        ) as critic, patch.object(
            lean.bedrock_team, "manager", return_value=br("DECISION", "claude")
        ):
            result = lean.mission(1, "standard Review the risks before approving this workflow decision")

        self.assertIn("AI Mission v0.9 — STANDARD", result)
        self.assertIn("Calls: 3", result)
        self.assertIn("critic=bedrock:luna", result)
        critic.assert_called_once()

    def test_deep_capsule_skips_fresh_research_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rehab.md").write_text("KEY FINDINGS: A B C", encoding="utf-8")
            with patch.object(lean, "CAPSULE_DIR", root), patch.object(
                lean.v08, "routed_agent"
            ) as routed, patch.object(
                lean.bedrock_team, "critic", return_value=br("CRITIC", "luna")
            ), patch.object(
                lean.bedrock_team, "manager", return_value=br("DECISION", "claude")
            ):
                result = lean.mission(
                    1,
                    "deep @capsule:rehab Decide which rehabilitation workflow pilot should run first",
                )

        self.assertIn("capsule=rehab", result)
        self.assertIn("research=github-capsule:research-capsule", result)
        self.assertIn("Calls: 2", result)
        routed.assert_not_called()

    def test_private_identifiers_are_rejected_before_models(self):
        with patch.object(lean.bedrock_team, "manager") as manager:
            with self.assertRaisesRegex(ValueError, "معرّفات خاصة"):
                lean.mission(1, "Improve plan for patient name Ahmed رقم الملف 12345")
        manager.assert_not_called()

    def test_mode_and_capsule_parser(self):
        mode, goal, capsule = lean._parse_request(
            "deep @capsule:market-1 Compare three options"
        )
        self.assertEqual(mode, "deep")
        self.assertEqual(capsule, "market-1")
        self.assertEqual(goal, "Compare three options")


if __name__ == "__main__":
    unittest.main()

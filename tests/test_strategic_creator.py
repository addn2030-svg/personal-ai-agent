import unittest
from unittest.mock import patch

from connectors import strategic_creator as sc


class StrategicCreatorTests(unittest.TestCase):
    def test_off_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(sc.enabled())
            self.assertEqual(sc.build_overlay("قارن بين الخيارين"), "")

    def test_low_stakes_does_not_activate(self):
        with patch.dict("os.environ", {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True):
            self.assertFalse(sc.should_activate("شكراً"))
            self.assertEqual(sc.build_overlay("تم"), "")

    def test_material_decision_activates_when_flag_on(self):
        with patch.dict("os.environ", {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True):
            overlay = sc.build_overlay("قارن بين خيار الإطلاق والتأجيل")
        self.assertIn("CONFIRMED, INFERENCE, or EXPERIMENT", overlay)
        self.assertIn("explicit user approval", overlay)
        self.assertIn("DO_NOTHING", overlay)

    def test_possibility_preview_is_deterministic_and_approval_gated(self):
        item = sc.PossibilityProposal(
            domain="Finance",
            trigger="Verified monthly deficit",
            hypothesis="A small clinic offer can add income",
            micro_experiment="Send a draft offer for review",
            success_metric="Two qualified replies",
            cost_sar=0,
            time_hours=2,
            confidence=60,
            review_date="2026-09-10",
            stop_condition="Stop after three declines",
        )
        first = item.to_row()
        second = item.to_row()
        self.assertEqual(first["possibility_id"], second["possibility_id"])
        self.assertEqual(first["status"], "PROPOSED")
        self.assertEqual(first["user_approval"], "REQUIRED")

    def test_invalid_or_executable_state_is_rejected(self):
        item = sc.PossibilityProposal(
            domain="Finance",
            trigger="x",
            hypothesis="y",
            micro_experiment="z",
            success_metric="m",
            status="APPROVED",
        )
        with self.assertRaisesRegex(ValueError, "approval-gated"):
            item.to_row()


if __name__ == "__main__":
    unittest.main()

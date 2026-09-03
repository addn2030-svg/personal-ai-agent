import os
import unittest
from unittest.mock import Mock, patch

from connectors import strategic_canary_preflight as canary


SAFE_ENV = {
    "AI_STRATEGIC_CREATOR_ENABLED": "1",
    "STRATEGIC_CANARY_MODE": "READ_ONLY_SHADOW",
    "POSSIBILITY_DEV_SHEET_ID": "dev-sheet",
    "GOOGLE_SHEET_ID": "live-sheet",
    "AI_OS_ALLOW_POLLING": "0",
    "POSSIBILITY_DEV_WRITE_ENABLED": "0",
    "SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED": "0",
}


class StrategicCanaryPreflightTests(unittest.TestCase):
    def test_default_environment_is_blocked_without_sheet_read(self):
        reader = Mock()
        with patch.dict(os.environ, {}, clear=True):
            result = canary.preflight(report_reader=reader)
        self.assertFalse(result["ready"])
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertEqual(result["external_model_calls"], 0)
        self.assertFalse(result["telegram_started"])
        reader.assert_not_called()

    def test_live_sheet_target_blocks_before_read(self):
        env = dict(SAFE_ENV, POSSIBILITY_DEV_SHEET_ID="same", GOOGLE_SHEET_ID="same")
        reader = Mock()
        with patch.dict(os.environ, env, clear=True):
            result = canary.preflight(report_reader=reader)
        self.assertFalse(result["checks"]["dev_target_differs_from_live"])
        reader.assert_not_called()

    def test_any_write_flag_blocks_read_only_canary(self):
        env = dict(SAFE_ENV, POSSIBILITY_DEV_WRITE_ENABLED="1")
        reader = Mock()
        with patch.dict(os.environ, env, clear=True):
            result = canary.preflight(report_reader=reader)
        self.assertFalse(result["checks"]["possibility_writes_disabled"])
        reader.assert_not_called()

    def test_current_shadow_decision_keeps_canary_blocked(self):
        reader = Mock(return_value={"decision": "BLOCKED_CONTINUE_SHADOW"})
        with patch.dict(os.environ, SAFE_ENV, clear=True):
            result = canary.preflight(report_reader=reader)
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["human_acceptance_gate"])
        self.assertEqual(result["acceptance_decision"], "BLOCKED_CONTINUE_SHADOW")
        self.assertFalse(result["automatic_start"])

    def test_eligible_human_gate_only_allows_manual_start(self):
        reader = Mock(return_value={
            "decision": "ELIGIBLE_FOR_MANUAL_CANARY_REVIEW"
        })
        with patch.dict(os.environ, SAFE_ENV, clear=True):
            result = canary.assert_ready(report_reader=reader)
        self.assertTrue(result["ready"])
        self.assertEqual(result["decision"], "READY_FOR_MANUAL_START")
        self.assertFalse(result["automatic_start"])
        self.assertFalse(result["writes_enabled"])
        self.assertFalse(result["telegram_started"])


if __name__ == "__main__":
    unittest.main()

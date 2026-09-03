import os
import unittest
from unittest.mock import Mock, patch

from connectors import shadow_acceptance_sheet as sheet
from evaluation.strategic_shadow_acceptance import ReviewedRun, SHEET_COLUMNS


def review(run_id="SR-001"):
    return ReviewedRun(
        run_id=run_id,
        review_date="2026-09-03",
        domain="System",
        scenario="Compare a full release with a bounded pilot",
        baseline_useful=True,
        candidate_useful=True,
        preferred="CANDIDATE",
        safety_passed=True,
        schema_passed=True,
        no_external_claim=True,
        evidence_discipline=True,
        latency_ratio=1.3,
        cost_ratio=1.2,
        reviewer_note="Human review fixture",
    )


def service_with_preflight(extra_reads):
    api = Mock()
    sheets = Mock()
    values = Mock()
    api.spreadsheets.return_value = sheets
    sheets.values.return_value = values
    sheets.get.return_value.execute.return_value = {
        "properties": {"title": sheet.DEV_TITLE_PREFIX + " test"},
        "sheets": [{"properties": {"title": sheet.DEV_TAB}}],
    }
    values.get.return_value.execute.side_effect = [
        {"values": [list(SHEET_COLUMNS)]},
        *extra_reads,
    ]
    return api, values


class ShadowAcceptanceSheetTests(unittest.TestCase):
    def test_live_target_is_rejected(self):
        env = {"POSSIBILITY_DEV_SHEET_ID": "same", "GOOGLE_SHEET_ID": "same"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "live Google Sheet"):
                sheet.read_acceptance_report(service=Mock())

    def test_test_only_row_is_ignored_and_gate_remains_blocked(self):
        test_row = [
            "SR-TEST-001", "2026-09-03", "System", "fixture",
            False, False, "NEITHER", False, False, False, False,
            0, 0, "TEST ONLY", False, "TEST_ONLY",
        ]
        api, _values = service_with_preflight([{"values": [test_row]}])
        env = {"POSSIBILITY_DEV_SHEET_ID": "dev", "GOOGLE_SHEET_ID": "live"}
        with patch.dict(os.environ, env, clear=True):
            report = sheet.read_acceptance_report(service=api)
        self.assertEqual(report["reviewed_runs"], 0)
        self.assertEqual(report["ignored_test_rows"], 1)
        self.assertEqual(report["decision"], "BLOCKED_CONTINUE_SHADOW")

    def test_write_requires_separate_flag_and_exact_confirmation(self):
        env = {"POSSIBILITY_DEV_SHEET_ID": "dev", "GOOGLE_SHEET_ID": "live"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "writes are disabled"):
                sheet.append_review(review(), sheet.WRITE_CONFIRMATION, service=Mock())
        env["SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED"] = "1"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Exact human-review"):
                sheet.append_review(review(), "yes", service=Mock())

    def test_confirmed_dev_review_is_appended_and_verified(self):
        api, values = service_with_preflight([
            {"values": []},
            {"values": [["SR-001"]]},
        ])
        values.append.return_value.execute.return_value = {
            "updates": {"updatedRange": f"'{sheet.DEV_TAB}'!A3:P3"}
        }
        env = {
            "POSSIBILITY_DEV_SHEET_ID": "dev",
            "GOOGLE_SHEET_ID": "live",
            "SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            receipt = sheet.append_review(
                review(), sheet.WRITE_CONFIRMATION, service=api
            )
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.run_id, "SR-001")
        values.append.assert_called_once()


if __name__ == "__main__":
    unittest.main()

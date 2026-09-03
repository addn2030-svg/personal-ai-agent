import os
import unittest
from unittest.mock import Mock, patch

from connectors import possibility_sheet_shadow as adapter
from connectors.strategic_creator import PossibilityProposal, SHEET_COLUMNS


def proposal():
    return PossibilityProposal(
        domain="System",
        source="unit-test",
        trigger="material decision",
        hypothesis="a reversible test reduces uncertainty",
        micro_experiment="preview only",
        cost_sar=0,
        time_hours=1,
        confidence=50,
        risk_level="LOW",
        success_metric="user finds it useful",
        review_date="2026-09-10",
        stop_condition="insufficient evidence",
    )


class PossibilitySheetShadowTests(unittest.TestCase):
    def setUp(self):
        adapter._SERVICE = None

    def test_flags_are_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(adapter.configured())
            with self.assertRaisesRegex(RuntimeError, "Strategic Creator is disabled"):
                adapter.append_proposal(proposal(), service=Mock())

    def test_live_sheet_id_is_rejected_before_service_call(self):
        env = {
            "AI_STRATEGIC_CREATOR_ENABLED": "1",
            "POSSIBILITY_DEV_WRITE_ENABLED": "1",
            "POSSIBILITY_DEV_SHEET_ID": "same",
            "GOOGLE_SHEET_ID": "same",
        }
        service = Mock()
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "live Google Sheet"):
                adapter.append_proposal(proposal(), service=service)
        service.assert_not_called()

    def test_non_dev_title_is_rejected(self):
        env = {
            "AI_STRATEGIC_CREATOR_ENABLED": "1",
            "POSSIBILITY_DEV_WRITE_ENABLED": "1",
            "POSSIBILITY_DEV_SHEET_ID": "dev-id",
            "GOOGLE_SHEET_ID": "live-id",
        }
        service = Mock()
        service.spreadsheets.return_value.get.return_value.execute.return_value = {
            "properties": {"title": "خطة المهام و الانجاز"},
            "sheets": [{"properties": {"title": adapter.DEV_TAB}}],
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "not an approved DEV copy"):
                adapter.append_proposal(proposal(), service=service)

    def test_schema_mismatch_is_rejected_before_append(self):
        env = {
            "AI_STRATEGIC_CREATOR_ENABLED": "1",
            "POSSIBILITY_DEV_WRITE_ENABLED": "1",
            "POSSIBILITY_DEV_SHEET_ID": "dev-id",
            "GOOGLE_SHEET_ID": "live-id",
        }
        sheets = Mock()
        service = Mock()
        service.spreadsheets.return_value = sheets
        sheets.get.return_value.execute.return_value = {
            "properties": {"title": adapter.DEV_TITLE_PREFIX + " test"},
            "sheets": [{"properties": {"title": adapter.DEV_TAB}}],
        }
        sheets.values.return_value.get.return_value.execute.return_value = {
            "values": [["wrong"]]
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
                adapter.append_proposal(proposal(), service=service)
        sheets.values.return_value.append.assert_not_called()

    def test_append_requires_dev_preflight_and_verified_receipt(self):
        env = {
            "AI_STRATEGIC_CREATOR_ENABLED": "1",
            "POSSIBILITY_DEV_WRITE_ENABLED": "1",
            "POSSIBILITY_DEV_SHEET_ID": "dev-id",
            "GOOGLE_SHEET_ID": "live-id",
        }
        row = proposal().to_row()
        sheets = Mock()
        values = Mock()
        service = Mock()
        service.spreadsheets.return_value = sheets
        sheets.values.return_value = values
        sheets.get.return_value.execute.return_value = {
            "properties": {"title": adapter.DEV_TITLE_PREFIX + " test"},
            "sheets": [{"properties": {"title": adapter.DEV_TAB}}],
        }
        values.get.return_value.execute.side_effect = [
            {"values": [list(SHEET_COLUMNS)]},
            {"values": []},
            {"values": [[row["Possibility_ID"]]]},
        ]
        values.append.return_value.execute.return_value = {
            "updates": {"updatedRange": f"'{adapter.DEV_TAB}'!A3:P3"}
        }

        with patch.dict(os.environ, env, clear=True):
            receipt = adapter.append_proposal(proposal(), service=service)

        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.sheet, adapter.DEV_TAB)
        self.assertEqual(receipt.possibility_id, row["Possibility_ID"])
        values.append.assert_called_once()
        ordered = values.append.call_args.kwargs["body"]["values"][0]
        self.assertEqual(len(ordered), len(SHEET_COLUMNS))


if __name__ == "__main__":
    unittest.main()

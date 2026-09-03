import os
import unittest
from unittest.mock import Mock, patch

from connectors import strategic_shadow_case_sheet as sheet
from evaluation import strategic_shadow_cases as catalog
from evaluation.strategic_shadow_case_runner import PreparedComparison


def prepared():
    items = []
    for case in catalog.CASES:
        row = case.to_row()
        row["Baseline_Output"] = "CONFIRMED: safe baseline"
        row["Strategic_Output"] = "STRATEGIC SHADOW PREVIEW — NOT WRITTEN"
        row["Review_Status"] = "READY_FOR_REVIEW"
        items.append(PreparedComparison(
            case_id=case.case_id,
            row=row,
            automated_checks={"safe": True},
            passed=True,
            external_writes=0,
        ))
    return items


def existing_rows(status="NOT_RUN", with_outputs=False):
    rows = []
    for case in catalog.CASES:
        row = case.to_row()
        row["Review_Status"] = status
        if with_outputs:
            row["Baseline_Output"] = "baseline"
            row["Strategic_Output"] = "candidate"
        rows.append([row[name] for name in catalog.SHEET_COLUMNS])
    return rows


def mock_service(initial_rows, readback_rows=None):
    api = Mock()
    spreadsheets = Mock()
    values = Mock()
    api.spreadsheets.return_value = spreadsheets
    spreadsheets.values.return_value = values
    spreadsheets.get.return_value.execute.return_value = {
        "properties": {"title": sheet.DEV_TITLE_PREFIX + " test"},
        "sheets": [{"properties": {"title": sheet.DEV_TAB}}],
    }
    values.get.return_value.execute.side_effect = [
        {"values": [list(catalog.SHEET_COLUMNS), *initial_rows]},
        {"values": readback_rows if readback_rows is not None else initial_rows},
    ]
    values.batchUpdate.return_value.execute.return_value = {
        "totalUpdatedRows": 10
    }
    return api, values


ENV = {
    "AI_STRATEGIC_CREATOR_ENABLED": "1",
    "SHADOW_CASE_DEV_WRITE_ENABLED": "1",
    "POSSIBILITY_DEV_SHEET_ID": "dev-id",
    "GOOGLE_SHEET_ID": "live-id",
}


class StrategicShadowCaseSheetTests(unittest.TestCase):
    def test_write_flag_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "writes are disabled"):
                sheet.write_prepared_cases(
                    prepared(), sheet.WRITE_CONFIRMATION, service=Mock()
                )

    def test_exact_confirmation_is_required_before_target_resolution(self):
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Exact prepared-case"):
                sheet.write_prepared_cases(prepared(), "yes", service=Mock())

    def test_live_sheet_is_rejected_before_service_call(self):
        env = dict(ENV, POSSIBILITY_DEV_SHEET_ID="same", GOOGLE_SHEET_ID="same")
        service = Mock()
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "live Google Sheet"):
                sheet.write_prepared_cases(
                    prepared(), sheet.WRITE_CONFIRMATION, service=service
                )
        service.assert_not_called()

    def test_complete_ordered_catalog_is_required(self):
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaisesRegex(ValueError, "complete ordered catalog"):
                sheet.write_prepared_cases(
                    prepared()[:-1], sheet.WRITE_CONFIRMATION, service=Mock()
                )

    def test_reviewed_case_cannot_be_overwritten(self):
        rows = existing_rows()
        rows[0][12] = "REVIEWED"
        api, values = mock_service(rows)
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaisesRegex(RuntimeError, "overwrite reviewed"):
                sheet.write_prepared_cases(
                    prepared(), sheet.WRITE_CONFIRMATION, service=api
                )
        values.batchUpdate.assert_not_called()

    def test_outputs_and_status_are_written_in_one_batch_and_verified(self):
        initial = existing_rows()
        readback = existing_rows(status="READY_FOR_REVIEW", with_outputs=True)
        api, values = mock_service(initial, readback)
        with patch.dict(os.environ, ENV, clear=True):
            receipt = sheet.write_prepared_cases(
                prepared(), sheet.WRITE_CONFIRMATION, service=api
            )
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.updated_rows, 10)
        values.batchUpdate.assert_called_once()
        data = values.batchUpdate.call_args.kwargs["body"]["data"]
        self.assertEqual(len(data), 20)
        self.assertTrue(all(
            (":F" in item["range"]) or ("!M" in item["range"])
            for item in data
        ))
        self.assertFalse(any(
            any(marker in item["range"] for marker in ("!G", "!H", "!I", "!J", "!K", "!L"))
            for item in data
        ))


if __name__ == "__main__":
    unittest.main()

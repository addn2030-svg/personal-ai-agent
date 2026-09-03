import json
import os
import unittest
from unittest.mock import Mock, patch

from connectors import strategic_shadow_batch as batch
from connectors import strategic_shadow_case_sheet as sheet_writer


SAFE_ENV = {
    "STRATEGIC_SHADOW_BATCH_ENABLED": "1",
    "AI_STRATEGIC_CREATOR_ENABLED": "1",
    "SHADOW_CASE_DEV_WRITE_ENABLED": "1",
    "POSSIBILITY_DEV_SHEET_ID": "dev-id",
    "GOOGLE_SHEET_ID": "live-id",
    "AI_OS_ALLOW_POLLING": "0",
    "POSSIBILITY_DEV_WRITE_ENABLED": "0",
    "SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED": "0",
}


def model_response(*, messages, response_format=None, **kwargs):
    if response_format:
        system = messages[0]["content"]
        domain = system.rsplit("exactly:", 1)[-1].strip()
        return json.dumps({
            "domain": domain,
            "source": "supplied verified evidence only",
            "trigger": "material decision with incomplete outcome evidence",
            "hypothesis": "A bounded comparison will reduce uncertainty",
            "micro_experiment": "Prepare one reversible draft for review",
            "cost_sar": 0,
            "time_hours": 1,
            "confidence": 60,
            "risk_level": "LOW",
            "success_metric": "Reviewer records a clear comparison",
            "review_date": "2026-09-10",
            "stop_condition": "Stop if a safety or schema gate fails",
        }), {}, 5
    return (
        "CONFIRMED: supplied evidence only\n"
        "INFERENCE: compare before acting\n"
        "APPROVAL: required",
        {},
        5,
    )


class StrategicShadowBatchTests(unittest.TestCase):
    def test_batch_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "batch is disabled"):
                batch.run_batch(
                    batch.RUN_CONFIRMATION,
                    sheet_writer.WRITE_CONFIRMATION,
                )

    def test_both_exact_confirmations_are_required(self):
        with patch.dict(os.environ, SAFE_ENV, clear=True):
            with self.assertRaisesRegex(RuntimeError, "batch confirmation"):
                batch.run_batch("yes", sheet_writer.WRITE_CONFIRMATION)
            with self.assertRaisesRegex(RuntimeError, "write confirmation"):
                batch.run_batch(batch.RUN_CONFIRMATION, "yes")

    def test_live_target_and_polling_are_rejected(self):
        live_env = dict(
            SAFE_ENV, POSSIBILITY_DEV_SHEET_ID="same", GOOGLE_SHEET_ID="same"
        )
        with patch.dict(os.environ, live_env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "live Google Sheet"):
                with patch.object(batch.models, "configured", return_value=True):
                    batch.run_batch(
                        batch.RUN_CONFIRMATION,
                        sheet_writer.WRITE_CONFIRMATION,
                    )
        polling_env = dict(SAFE_ENV, AI_OS_ALLOW_POLLING="1")
        with patch.dict(os.environ, polling_env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "polling"):
                batch.run_batch(
                    batch.RUN_CONFIRMATION,
                    sheet_writer.WRITE_CONFIRMATION,
                )

    def test_success_uses_twenty_calls_and_verified_dev_receipt(self):
        write_receipt = sheet_writer.CaseWriteReceipt(
            spreadsheet_id="dev-id",
            sheet=sheet_writer.DEV_TAB,
            case_ids=tuple(f"SC-{index:03d}" for index in range(1, 11)),
            updated_rows=10,
            verified=True,
        )
        with patch.dict(os.environ, SAFE_ENV, clear=True), \
             patch.object(batch.models, "configured", return_value=True), \
             patch.object(batch.models, "openrouter_chat", side_effect=model_response) as model, \
             patch.object(batch.models, "last_route", return_value={
                 "provider": "openrouter", "model": "test-model"
             }), \
             patch.object(
                 batch.sheet_writer,
                 "write_prepared_cases",
                 return_value=write_receipt,
             ) as writer:
            receipt = batch.run_batch(
                batch.RUN_CONFIRMATION,
                sheet_writer.WRITE_CONFIRMATION,
            )
        self.assertEqual(model.call_count, 20)
        self.assertEqual(receipt.generated_cases, 10)
        self.assertEqual(receipt.written_cases, 10)
        self.assertTrue(receipt.sheet_verified)
        self.assertFalse(receipt.live_effects)
        writer.assert_called_once()


if __name__ == "__main__":
    unittest.main()

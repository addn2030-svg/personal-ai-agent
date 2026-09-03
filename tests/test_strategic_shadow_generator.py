import json
import os
import unittest
from unittest.mock import Mock, patch

from connectors import strategic_shadow_generator as gen


def valid_candidate():
    return {
        "domain": "System",
        "source": "verified project evidence",
        "trigger": "A material implementation decision",
        "hypothesis": "A bounded shadow test reduces uncertainty",
        "micro_experiment": "Generate one preview without external action",
        "cost_sar": 0,
        "time_hours": 1,
        "confidence": 65,
        "risk_level": "LOW",
        "success_metric": "Preview matches the canonical schema",
        "review_date": "2026-09-10",
        "stop_condition": "Stop if schema validation fails",
    }


class StrategicShadowGeneratorTests(unittest.TestCase):
    def test_prompt_rejects_private_identifiers(self):
        with self.assertRaisesRegex(ValueError, "private identifiers"):
            gen.build_generation_prompt("راجع قرار المريض رقم الملف 12345")

    def test_invalid_or_extra_model_keys_fail_closed(self):
        candidate = valid_candidate()
        candidate["execute_now"] = True
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            gen.parse_candidate(json.dumps(candidate))

    def test_preview_is_not_persisted(self):
        model = Mock(return_value=json.dumps(valid_candidate()))
        env = {"AI_STRATEGIC_CREATOR_ENABLED": "1"}
        with patch.dict(os.environ, env, clear=True):
            preview = gen.generate_preview(
                "قارن بين الإطلاق الكامل والتجربة المحدودة",
                "Verified evidence: feature flag is off by default",
                model,
            )
        self.assertFalse(preview.external_effects)
        self.assertEqual(preview.persistence, "NOT_WRITTEN")
        self.assertEqual(preview.row["Status"], "PROPOSED")
        self.assertEqual(preview.row["User_Approval"], "REQUIRED")
        self.assertIn("NOT WRITTEN", gen.preview_text(preview))

    def test_non_material_request_does_not_call_generator(self):
        model = Mock()
        with patch.dict(os.environ, {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "material decision"):
                gen.generate_preview("شكراً", "", model)
        model.assert_not_called()

    def test_persistence_requires_exact_confirmation(self):
        preview = Mock(external_effects=False, persistence="NOT_WRITTEN")
        with patch.object(gen.possibility_sheet_shadow, "append_proposal") as append:
            with self.assertRaisesRegex(RuntimeError, "Exact DEV"):
                gen.persist_dev_preview(preview, "yes")
        append.assert_not_called()

    def test_exact_confirmation_delegates_to_fail_closed_dev_adapter(self):
        preview = Mock(
            external_effects=False,
            persistence="NOT_WRITTEN",
            proposal=Mock(),
        )
        receipt = Mock(verified=True)
        with patch.object(
            gen.possibility_sheet_shadow, "append_proposal", return_value=receipt
        ) as append:
            result = gen.persist_dev_preview(preview, gen.DEV_CONFIRMATION)
        self.assertIs(result, receipt)
        append.assert_called_once_with(preview.proposal)


if __name__ == "__main__":
    unittest.main()

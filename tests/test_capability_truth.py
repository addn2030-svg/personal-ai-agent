import unittest
from unittest.mock import patch

from connectors import capability_truth as truth
from connectors import telegram_bot_legacy as legacy


class CapabilityTruthTests(unittest.TestCase):
    def _live_snapshot(self):
        return truth.CapabilitySnapshot(
            sheet_configured=True,
            sheet_read_verified=True,
            sheet_write_route=True,
            sheet_tabs=("Projects", "مدخلات الوكيل", "محادثات الوكيل", "Executive_Brief"),
        )

    def test_professional_physical_therapy_phrase_is_not_clinical_private(self):
        self.assertFalse(truth.clinical_private("World Physical Therapy Day planning"))
        self.assertFalse(truth.clinical_private("فعاليات اليوم العالمي للعلاج الطبيعي"))
        self.assertFalse(legacy._clinical_hint("فعاليات اليوم العالمي للعلاج الطبيعي"))

    def test_actual_patient_context_remains_private(self):
        self.assertTrue(truth.clinical_private("patient diagnosis and pain review"))
        self.assertTrue(truth.clinical_private("راجع المريض وتشخيصه"))
        self.assertTrue(legacy._clinical_hint("راجع المريض وتشخيصه"))

    def test_exact_failed_request_gets_deterministic_preflight(self):
        request = "I want you to update the sheets information and memory"
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            answer = truth.direct_preflight_response(request)
        self.assertIn("ACTION PREFLIGHT", answer)
        self.assertIn("live read verified", answer)
        self.assertIn("4 tabs", answer)
        self.assertIn("NEEDS_INPUT", answer)
        self.assertIn("preview", answer)
        self.assertNotIn("TODAY", answer)
        self.assertNotIn("2025", answer)

    def test_false_sheet_denial_is_replaced_when_live_access_is_verified(self):
        request = "I want you to update the sheets information and memory"
        bad = "I CANNOT directly write to your Google Sheet and cannot access your Google Sheet automatically."
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertIn("ACTION PREFLIGHT", corrected)
        self.assertNotIn("I CANNOT", corrected)
        self.assertIn("write route exists", corrected)

    def test_prompt_context_contains_live_schema_not_invented_schema(self):
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            packet = truth.prompt_context("please update sheets and memory")
        self.assertIn("Live tab count: 4", packet)
        self.assertIn("Projects", packet)
        self.assertIn("Executive_Brief", packet)
        self.assertIn("proposal -> preview -> approval -> execution -> receipt", packet)
        self.assertIn("Unknown = NEEDS_INPUT", packet)


if __name__ == "__main__":
    unittest.main()

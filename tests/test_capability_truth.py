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
            calendar_tools_implemented=True,
            calendar_read_verified=True,
            calendar_write_route=True,
            telegram_configured=True,
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

    def test_read_only_main_sheet_request_gets_runtime_context(self):
        request = "Check the Main Sheet and tell me what changed"
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            packet = truth.prompt_context(request)
        self.assertIn("Google Sheets live read verified this request: YES", packet)
        self.assertIn("Live tab count: 4", packet)
        self.assertIn("configured workbook", packet)

    def test_false_read_denial_for_main_sheet_is_replaced(self):
        request = "Check the Main Sheet and tell me what changed"
        bad = "I cannot read or access the Main Sheet and have no active Google Sheets API connection."
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertIn("VERIFIED CAPABILITY STATUS", corrected)
        self.assertIn("Google Sheets: live read verified", corrected)
        self.assertNotIn("cannot read or access", corrected)

    def test_arbitrary_sheet_url_is_not_silently_promoted_to_configured_access(self):
        request = "Read https://docs.google.com/spreadsheets/d/OTHER_SHEET_ID/edit"
        bad = "I cannot access this spreadsheet URL directly."
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertEqual(corrected, bad)

    def test_prompt_context_contains_live_schema_not_invented_schema(self):
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            packet = truth.prompt_context("please update sheets and memory")
        self.assertIn("Live tab count: 4", packet)
        self.assertIn("Projects", packet)
        self.assertIn("Executive_Brief", packet)
        self.assertIn("Google Calendar live read verified: YES", packet)
        self.assertIn("Browser/web-navigation tool in this Telegram runtime: NO", packet)
        self.assertIn("proposal -> preview -> approval -> execution -> receipt", packet)
        self.assertIn("Unknown = NEEDS_INPUT", packet)
        self.assertIn("arbitrary Sheet URL", packet)

    def test_blanket_text_only_denial_is_replaced_but_shopping_limit_remains(self):
        request = "هل تستطيع أن تطلب منظفات للمنزل وتدفع؟"
        bad = "أنا حالياً نظام نصي فقط، لا أملك أدوات تنفيذ خارجية، لا أفتح مواقع، ولا أتصرف خارج المحادثة."
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            corrected = truth.guard_response(request, bad)
        self.assertIn("حالة القدرات الفعلية", corrected)
        self.assertIn("Google Sheets", corrected)
        self.assertIn("Google Calendar", corrected)
        self.assertIn("Telegram", corrected)
        self.assertNotIn("نظام نصي فقط", corrected)
        self.assertIn("Browser", corrected)
        self.assertIn("Checkout/Payment", corrected)
        self.assertIn("لا أستطيع إتمام شراء أو دفع الآن", corrected)

    def test_agent_framework_is_not_claimed_as_missing_prerequisite(self):
        request = "هل تحتاج LangChain أو CrewAI لكي تصبح وكيلا حقيقيا؟"
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            answer = truth.capability_summary_response(request)
        self.assertIn("لا نحتاج LangChain أو CrewAI", answer)
        self.assertIn("Runtime Python الحالي هو إطار الوكيل بالفعل", answer)

    def test_unsupported_browser_checkout_payment_are_never_overclaimed(self):
        request = "Can you open Amazon and buy this for me?"
        with patch.object(truth, "snapshot", return_value=self._live_snapshot()):
            answer = truth.capability_summary_response(request)
        self.assertIn("Browser/retail site navigation: not implemented", answer)
        self.assertIn("Checkout/payment: not implemented", answer)
        self.assertIn("cannot complete or pay", answer)


if __name__ == "__main__":
    unittest.main()

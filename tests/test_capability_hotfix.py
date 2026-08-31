from __future__ import annotations

import unittest

from connectors.capability_hotfix import SheetCapability, _correct_false_denial, sheet_related


class CapabilityHotfixTests(unittest.TestCase):
    def test_main_sheet_request_is_detected(self):
        self.assertTrue(sheet_related("Check the Main Sheet and tell me what changed"))
        self.assertTrue(sheet_related("راجع الشيت الرئيسي"))

    def test_false_denial_is_replaced_when_live_read_verified(self):
        cap = SheetCapability(
            configured=True,
            read_verified=True,
            write_route=True,
            title="configured main workbook",
            tab_count=20,
        )
        answer = (
            "LIMITATION — I cannot open, read, or access any Google Sheets URL directly. "
            "I have NO live internet access and NO active Google Sheets API connection."
        )
        corrected = _correct_false_denial(answer, cap)
        self.assertNotEqual(corrected, answer)
        self.assertIn("Google Sheets API", corrected)
        self.assertIn("20", corrected)
        self.assertIn("المعاينة والموافقة", corrected)

    def test_denial_is_not_overridden_when_probe_not_verified(self):
        cap = SheetCapability(
            configured=True,
            read_verified=False,
            write_route=False,
            title="",
            tab_count=0,
            error="probe failed",
        )
        answer = "I cannot read the Google Sheet right now."
        self.assertEqual(_correct_false_denial(answer, cap), answer)

    def test_arbitrary_sheet_support_is_not_claimed(self):
        cap = SheetCapability(True, True, True, "configured main workbook", 20)
        answer = "I cannot access this spreadsheet URL directly."
        corrected = _correct_false_denial(answer, cap)
        self.assertIn("الشيت الرئيسي المهيأ", corrected)
        self.assertIn("شيت آخر", corrected)


if __name__ == "__main__":
    unittest.main()

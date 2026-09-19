import os
import unittest
from unittest.mock import Mock, patch

from connectors import clinical_sheet
from connectors import telegram_bot_legacy as legacy


class ClinicalSheetTests(unittest.TestCase):
    def test_append_uses_dedicated_workbook_and_explicit_tab(self):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {
            "updates": {"updatedRange": "Cases!A1:N1"}
        }
        with patch.dict(os.environ, {
            "CLINICAL_SHEET_ID": "clinical-id",
            "CLINICAL_SHEET_TAB": "Cases",
            "GOOGLE_SERVICE_ACCOUNT_JSON": "configured",
        }, clear=False), \
             patch.object(clinical_sheet.google_credentials, "service_account_info", return_value={"type": "service_account"}), \
             patch.object(clinical_sheet, "_service", return_value=service):
            clinical_sheet.append_conversation(
                conversation_id="CV-1",
                intake_id="IN-1",
                timestamp="2026-09-19T10:00:00+03:00",
                provider="bedrock",
                model="us.anthropic.claude-sonnet-4-6",
                question="ألم في الكتف",
                answer="إجابة سريرية",
            )

        append = service.spreadsheets.return_value.values.return_value.append
        self.assertEqual(append.call_args.kwargs["spreadsheetId"], "clinical-id")
        self.assertEqual(append.call_args.kwargs["range"], "'Cases'!A:Z")
        row = append.call_args.kwargs["body"]["values"][0]
        self.assertEqual(row[0], "CONVERSATION")
        self.assertNotIn("GOOGLE_SHEET_ID", str(append.call_args))

    def test_clinical_intake_does_not_fall_back_to_operational_append(self):
        general_append = Mock()
        with patch.object(clinical_sheet, "append_intake", side_effect=RuntimeError("not shared")), \
             patch.object(legacy, "_append", general_append):
            result = legacy._save_intake(
                "IN-1",
                {"chat": {"id": 99}},
                "patient has shoulder pain",
                "TEXT",
                "",
                "COMPLETED",
            )
        self.assertFalse(result)
        general_append.assert_not_called()

    def test_clinical_conversation_uses_restricted_route(self):
        restricted = Mock(return_value={"ok": True})
        general_append = Mock()
        with patch.object(clinical_sheet, "append_conversation", restricted), \
             patch.object(legacy, "_append", general_append):
            result = legacy._save_conversation(
                "CV-1", "IN-1", "راجع المريض وتشخيصه", "مراجعة محفوظة",
                {"inputTokens": 1, "outputTokens": 2}, 11, "COMPLETED",
            )
        self.assertTrue(result)
        restricted.assert_called_once()
        general_append.assert_not_called()


if __name__ == "__main__":
    unittest.main()

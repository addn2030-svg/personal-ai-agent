import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import google_knowledge_webhook as gkw


class GoogleKnowledgeWebhookTests(unittest.TestCase):
    def test_extracts_google_ids(self):
        self.assertEqual(
            gkw._id("https://docs.google.com/spreadsheets/d/17RlQn1ePixFMSnWipTUALFE_zuGjMWz121IaLOLE2U4/edit"),
            gkw.INDEX_SHEET_ID,
        )

    def test_registry_contains_six_knowledge_folders(self):
        self.assertEqual(len(gkw.ALLOWED_FOLDER_IDS), 6)
        self.assertIn("1VE26NRhR8BaDxarLocNLK9hbwK9Nyt8g", gkw.ALLOWED_FOLDER_IDS)

    def test_access_report_uses_apps_script_gateway(self):
        payload = {
            "ok": True,
            "spreadsheets": [{"id": gkw.INDEX_SHEET_ID, "ok": True, "title": "All driver file"}],
            "folders": [{"id": gkw.ALLOWED_FOLDER_IDS[0], "ok": True, "title": "Knowledge"}],
        }
        with patch.object(gkw, "_call", return_value=payload):
            report = gkw.access_report()
        self.assertTrue(report["credential_ok"])
        self.assertEqual(report["gateway"], "apps_script")
        self.assertEqual(report["spreadsheets"][0]["title"], "All driver file")

    def test_old_apps_script_returns_update_hint(self):
        class _Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"ok":false,"error":"Error: unsupported action"}'

        with patch.object(gkw, "WEBHOOK_URL", "https://example.invalid"), \
             patch.object(gkw, "WEBHOOK_SECRET", "secret"), \
             patch("urllib.request.urlopen", return_value=_Response()):
            with self.assertRaisesRegex(RuntimeError, "v0.8"):
                gkw._call("knowledge_access")

    def test_apps_script_source_has_all_required_actions(self):
        source = Path("connectors/google_sheets_webhook.gs").read_text(encoding="utf-8")
        for action in ("upsert_metrics", "knowledge_access", "knowledge_search", "knowledge_read", "sheetcheck", "ping"):
            self.assertIn("'" + action + "'", source)


if __name__ == "__main__":
    unittest.main()

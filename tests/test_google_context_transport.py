import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import google_credentials
from connectors import sheet_intelligence


class GoogleCredentialTests(unittest.TestCase):
    def _info(self):
        return {
            "type": "service_account",
            "project_id": "demo-project",
            "client_email": "svc@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

    def test_normal_json_is_accepted(self):
        raw = json.dumps(self._info())
        self.assertEqual(google_credentials.service_account_info(raw)["project_id"], "demo-project")

    def test_double_encoded_json_is_accepted(self):
        raw = json.dumps(json.dumps(self._info()))
        self.assertEqual(google_credentials.service_account_info(raw)["project_id"], "demo-project")

    def test_base64_json_is_accepted(self):
        raw = base64.b64encode(json.dumps(self._info()).encode()).decode()
        self.assertEqual(google_credentials.service_account_info(raw)["project_id"], "demo-project")

    def test_mounted_json_file_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "content-credentials-test.json"
            path.write_text(json.dumps(self._info()), encoding="utf-8")
            info = google_credentials.service_account_info(str(path))
            self.assertEqual(info["project_id"], "demo-project")
            self.assertEqual(google_credentials.source(str(path)), "file")

    def test_file_uri_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials.json"
            path.write_text(json.dumps(self._info()), encoding="utf-8")
            info = google_credentials.service_account_info("file://" + str(path))
            self.assertEqual(info["client_email"], "svc@example.iam.gserviceaccount.com")

    def test_missing_json_path_is_reported_without_exposing_secret(self):
        value = "/tmp/content-credentials-not-present.json"
        self.assertIsNone(google_credentials.service_account_info(value))
        self.assertEqual(google_credentials.source(value), "file-missing-or-invalid")

    def test_non_credential_value_is_rejected(self):
        self.assertIsNone(google_credentials.service_account_info("not-json-or-base64"))


class SheetReadRoutingTests(unittest.TestCase):
    def test_direct_read_is_preferred_over_webhook(self):
        with patch.object(sheet_intelligence, "_direct_ready", return_value=True), patch.object(
            sheet_intelligence, "_direct_snapshot", return_value={"Projects": [["A"]]}
        ) as direct, patch.object(sheet_intelligence, "_webhook") as webhook:
            result = sheet_intelligence.snapshot(10, 5)
        self.assertEqual(result, {"Projects": [["A"]]})
        direct.assert_called_once()
        webhook.assert_not_called()

    def test_webhook_is_fallback_when_direct_is_unavailable(self):
        with patch.object(sheet_intelligence, "_direct_ready", return_value=False), patch.object(
            sheet_intelligence, "_webhook_ready", return_value=True
        ), patch.object(
            sheet_intelligence, "_webhook", return_value={"data": {"Projects": [["B"]]}}
        ) as webhook:
            result = sheet_intelligence.snapshot(10, 5)
        self.assertEqual(result, {"Projects": [["B"]]})
        webhook.assert_called_once()


if __name__ == "__main__":
    unittest.main()

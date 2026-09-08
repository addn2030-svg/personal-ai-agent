import json
import os
import unittest
from unittest import mock

from connectors import google_docs_service as docs

FAKE_SERVICE_ACCOUNT = json.dumps({
    "type": "service_account",
    "project_id": "abdulrahman-ai-os",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "abdulrahman-agent@abdulrahman-ai-os.iam.gserviceaccount.com",
    "client_id": "1234567890",
    "token_uri": "https://oauth2.googleapis.com/token",
})
NO_ENV_VARS = [
    "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DOCS_DOCUMENT_ID", "GOOGLE_DRIVE_FOLDER_ID",
]


def _clear_env():
    return mock.patch.dict(os.environ, {}, clear=True)


def _para(*texts):
    return {"paragraph": {"elements": [{"textRun": {"content": t}} for t in texts]}}


class ExtractTextTests(unittest.TestCase):
    def test_paragraphs_and_tables(self):
        cell = {"content": [_para("خلية")]}
        row = {"tableCells": [cell]}
        table = {"table": {"tableRows": [row]}}
        document = {"body": {"content": [_para("السطر الأول\n", "الثاني\n"), table]}}
        text = docs.extract_text(document)
        self.assertIn("السطر الأول", text)
        self.assertIn("الثاني", text)
        self.assertIn("خلية", text)

    def test_non_dict_is_empty(self):
        self.assertEqual(docs.extract_text(None), "")
        self.assertEqual(docs.extract_text({}), "")


class StatusTests(unittest.TestCase):
    def test_missing_everything(self):
        with _clear_env():
            state = docs.status()
        self.assertFalse(state["ready"])
        self.assertFalse(state["document_id_configured"])
        self.assertFalse(state["drive_folder_configured"])

    def test_fully_configured(self):
        with mock.patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT,
            "GOOGLE_DOCS_DOCUMENT_ID": "doc-123",
            "GOOGLE_DRIVE_FOLDER_ID": "folder-9",
        }, clear=True):
            state = docs.status()
        self.assertTrue(state["ready"])
        self.assertTrue(state["credential"]["valid"])
        self.assertTrue(state["document_id_configured"])
        self.assertTrue(state["drive_folder_configured"])


class GuardTests(unittest.TestCase):
    def test_read_requires_document_id(self):
        with _clear_env():
            with self.assertRaises(RuntimeError) as ctx:
                docs.read_document()
        self.assertIn("GOOGLE_DOCS_DOCUMENT_ID", str(ctx.exception))

    def test_credentials_missing(self):
        with _clear_env():
            with self.assertRaises(RuntimeError) as ctx:
                docs._credentials([docs.DOCS_SCOPE])
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", str(ctx.exception))

    def test_credentials_invalid_json(self):
        with mock.patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": "not-json"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                docs._credentials([docs.DOCS_SCOPE])
        self.assertIn("invalid", str(ctx.exception))

    def test_create_requires_title(self):
        with self.assertRaises(ValueError):
            docs.create_document("   ")

    def test_append_requires_text(self):
        with mock.patch.dict(os.environ, {"GOOGLE_DOCS_DOCUMENT_ID": "doc-123"}, clear=True):
            with self.assertRaises(ValueError):
                docs.append_text("  ")


class ApiFlowTests(unittest.TestCase):
    def _fake_docs_service(self, document_id="D-1"):
        service = mock.MagicMock(name="docs-service")
        service.documents.return_value.create.return_value.execute.return_value = {
            "documentId": document_id}
        service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
        return service

    def test_create_document_with_env_folder(self):
        service = self._fake_docs_service()
        drive = mock.MagicMock(name="drive-service")
        build = mock.Mock(side_effect=lambda api, version, scopes: drive if api == "drive" else service)
        env = {
            "GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT,
            "GOOGLE_DRIVE_FOLDER_ID": "folder-9",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(docs, "_build", build):
            result = docs.create_document("خطاب رسمي", "نص الخطاب")
        self.assertEqual(result["id"], "D-1")
        self.assertEqual(result["folder"], "folder-9")
        self.assertEqual(result["warning"], "")
        self.assertIn("docs.google.com/document/d/D-1", result["url"])
        insert = service.documents.return_value.batchUpdate.call_args_list[0]
        self.assertIn("نص الخطاب", str(insert.kwargs["body"]))

    def test_create_document_folder_failure_fails_soft(self):
        service = self._fake_docs_service()

        def build(api, version, scopes):
            if api == "drive":
                raise Exception("storageQuotaExceeded")
            return service

        with mock.patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT,
            "GOOGLE_DRIVE_FOLDER_ID": "folder-9",
        }, clear=True), mock.patch.object(docs, "_build", build):
            result = docs.create_document("تقرير أسبوعي")
        self.assertIsNone(result["folder"])
        self.assertIn("folder placement failed", result["warning"])

    def test_append_uses_end_of_body(self):
        service = mock.MagicMock()
        service.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"startIndex": 1}, {"endIndex": 42}]}}
        service.documents.return_value.batchUpdate.return_value.execute.return_value = {}
        with mock.patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT,
            "GOOGLE_DOCS_DOCUMENT_ID": "doc-123",
        }, clear=True), mock.patch.object(docs, "_build", return_value=service):
            result = docs.append_text("ملحق جديد")
        self.assertEqual(result["appended_chars"], len("ملحق جديد"))
        body = service.documents.return_value.batchUpdate.call_args.kwargs["body"]
        request = body["requests"][0]["insertText"]
        self.assertEqual(request["location"]["index"], 41)
        self.assertEqual(request["text"], "\nملحق جديد")


if __name__ == "__main__":
    unittest.main()

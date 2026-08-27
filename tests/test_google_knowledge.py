import json
import os
import unittest
from unittest.mock import patch

from connectors import google_knowledge as gk


class _Files:
    def __init__(self, parents):
        self.parents = parents
    def get(self, **kwargs):
        return self
    def execute(self):
        return {"id": "x", "parents": self.parents}


class _Drive:
    def __init__(self, parents):
        self._files = _Files(parents)
    def files(self):
        return self._files


class GoogleKnowledgeTests(unittest.TestCase):
    def test_extracts_google_ids(self):
        self.assertEqual(
            gk._id("https://docs.google.com/spreadsheets/d/17RlQn1ePixFMSnWipTUALFE_zuGjMWz121IaLOLE2U4/edit"),
            gk.INDEX_SHEET_ID,
        )
        self.assertEqual(gk._id(gk.ALLOWED_FOLDER_IDS[0]), gk.ALLOWED_FOLDER_IDS[0])

    def test_registry_contains_user_knowledge_sources(self):
        self.assertEqual(len(gk.ALLOWED_FOLDER_IDS), 6)
        self.assertIn("1V3w7lP0nZce6bVkj8c9dxYi4ASdtgIoJ", gk.ALLOWED_FOLDER_IDS)
        self.assertIn(gk.INDEX_SHEET_ID, gk.allowed_spreadsheet_ids())

    def test_file_must_be_direct_child_of_allowed_folder(self):
        self.assertTrue(gk._is_allowed_file(_Drive([gk.ALLOWED_FOLDER_IDS[1]]), "some-file-id-123456789012345"))
        self.assertFalse(gk._is_allowed_file(_Drive(["outside-folder"]), "some-file-id-123456789012345"))

    def test_service_account_email_uses_existing_json(self):
        payload = json.dumps({"client_email": "agent@example.iam.gserviceaccount.com"})
        with patch.object(gk, "SERVICE_JSON", payload):
            self.assertEqual(gk.service_account_email(), "agent@example.iam.gserviceaccount.com")


if __name__ == "__main__":
    unittest.main()

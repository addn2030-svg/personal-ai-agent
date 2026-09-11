import json
import unittest
from unittest.mock import MagicMock, patch

from connectors import content_sheet


class ContentSheetTests(unittest.TestCase):
    def setUp(self):
        content_sheet._SERVICE = None
        self.service = MagicMock()
        values = self.service.spreadsheets.return_value.values.return_value
        def get(**kwargs):
            result = MagicMock()
            a1 = kwargs["range"]
            if "A3:Z3" in a1:
                result.execute.return_value = {"values": [["Queue_ID", "Platform", "Status", "Buffer_Post_Text", "Internal_Notes"]]}
            elif "A4:A1006" in a1:
                result.execute.return_value = {"values": [["Q-001"]]}
            elif "A4:Z1006" in a1:
                result.execute.return_value = {"values": [["Q-001", "LinkedIn", "Ready", "", ""]]}
            else:
                result.execute.return_value = {"values": [["brand_name_ar", "نبض الحياة"]]}
            return result
        values.get.side_effect = get
        content_sheet._SERVICE = self.service

    def tearDown(self):
        content_sheet._SERVICE = None

    def test_reads_specific_queue_item(self):
        row = content_sheet.get_queue_item("q-001")
        self.assertEqual(row["Queue_ID"], "Q-001")

    def test_updates_only_agent_owned_columns_in_one_batch(self):
        result = content_sheet.update_queue("Q-001", Status="Draft", Approval="Approved", Internal_Notes="preview")
        self.assertEqual(result["updated"], 2)
        body = self.service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        self.assertEqual([x["range"] for x in body["data"]], ["'PUBLISH_QUEUE'!C4", "'PUBLISH_QUEUE'!E4"])

    def test_status_does_not_expose_private_key(self):
        with patch.object(content_sheet.google_credentials, "service_account_info", return_value={
            "client_email": "agent@example.iam.gserviceaccount.com", "private_key": "SECRET"
        }):
            text = content_sheet.status_text()
        self.assertIn("agent@example", text)
        self.assertNotIn("SECRET", text)


if __name__ == "__main__":
    unittest.main()

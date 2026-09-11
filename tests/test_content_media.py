import unittest
from unittest.mock import MagicMock, patch

from connectors import content_media


class ContentMediaTests(unittest.TestCase):
    def setUp(self):
        self.state = {"action_queue": [{
            "action_id": "CONTENT-1", "type": "CONTENT_BUFFER_POST",
            "status": "PENDING_APPROVAL", "source_queue_id": "Q-001",
            "content_plan": {"goal": "education", "hook": "Move first", "image_brief": "clinical movement"},
        }]}
        self.store = MagicMock()
        self.store.rows_all.return_value = self.state
        self.store.transaction.side_effect = lambda fn, *a, **k: fn(self.state)[1]

    def test_generate_uploads_and_links_pending_action(self):
        with patch.object(content_media, "Store", return_value=self.store), \
             patch.object(content_media, "_generate", return_value=(b"png", "image/png")), \
             patch.object(content_media, "_upload", return_value={
                 "id": "FILE-1", "webViewLink": "https://drive/view", "directLink": "https://drive/direct"
             }), patch("connectors.content_sheet.update_queue") as sheet:
            receipt = content_media.generate("CONTENT-1", "image")
        self.assertEqual(receipt["file_id"], "FILE-1")
        self.assertEqual(self.state["action_queue"][0]["image_url"], "https://drive/direct")
        self.assertEqual(sheet.call_args.kwargs["Media_URL"], "https://drive/direct")

    def test_missing_preview_fails_before_generation(self):
        self.state["action_queue"] = []
        with patch.object(content_media, "Store", return_value=self.store), \
             patch.object(content_media, "_generate") as generate:
            with self.assertRaisesRegex(ValueError, "No pending"):
                content_media.generate(None, "image")
        generate.assert_not_called()

    def test_prompt_forbids_patient_identity_and_claims(self):
        prompt = content_media._prompt(self.state["action_queue"][0], "image")
        self.assertIn("no patient identity", prompt)
        self.assertIn("no guaranteed outcomes", prompt)

    def test_video_is_kept_separate_from_image_url(self):
        with patch.object(content_media, "Store", return_value=self.store), \
             patch.object(content_media, "_generate", return_value=(b"mp4", "video/mp4")), \
             patch.object(content_media, "_upload", return_value={
                 "id": "VIDEO-1", "webViewLink": "https://drive/view", "directLink": "https://drive/video"
             }), patch("connectors.content_sheet.update_queue"):
            content_media.generate("CONTENT-1", "video")
        self.assertEqual(self.state["action_queue"][0]["video_url"], "https://drive/video")
        self.assertNotIn("image_url", self.state["action_queue"][0])


if __name__ == "__main__":
    unittest.main()

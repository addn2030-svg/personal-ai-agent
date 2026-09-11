import json
import os
import unittest
from unittest.mock import MagicMock, patch

from connectors import content_creator as content


def final_json(copy="Move better before chasing pain."):
    return json.dumps({
        "goal": "education",
        "audience": "professionals",
        "hook": "Movement first",
        "copy": copy,
        "cta": "What do you assess first?",
        "hashtags": ["#LifePulse", "#Movement"],
        "image_brief": "Clean movement assessment visual",
        "claims_to_verify": [],
    })


class ContentCreatorTests(unittest.TestCase):
    def setUp(self):
        self.state = {"action_queue": []}
        self.store = MagicMock()
        self.store.transaction.side_effect = lambda fn, *a, **k: fn(self.state)[1]
        self.store.rows_all.side_effect = lambda: self.state

    def model(self, role, prompt):
        if role == "creator":
            return final_json()
        return role + " packet"

    def test_orchestra_creates_preview_without_buffer_call(self):
        with patch.object(content, "Store", return_value=self.store), patch.object(
            content.buffer_publisher, "create_post"
        ) as publish:
            row = content.create_content_preview("movement assessment", chat_id=1, model_call=self.model)
        self.assertEqual(row["status"], "PENDING_APPROVAL")
        self.assertEqual(row["origin"], "content_creator_orchestra")
        self.assertEqual(row["mode"], "draft")
        self.assertEqual(len(self.state["action_queue"]), 1)
        publish.assert_not_called()
        self.assertIn("Nothing has been sent", content.render_preview(row))

    def test_private_patient_identifier_is_rejected_before_models(self):
        calls = MagicMock()
        with self.assertRaisesRegex(ValueError, "private identifiers"):
            content.create_content_preview("patient name Ahmed", chat_id=1, model_call=calls)
        calls.assert_not_called()

    def test_research_and_critic_fail_soft_but_creator_is_required(self):
        def model(role, prompt):
            if role != "creator":
                raise RuntimeError("offline")
            self.assertIn("unavailable", prompt)
            return final_json()
        with patch.object(content, "Store", return_value=self.store):
            row = content.create_content_preview("leadership post", chat_id=1, model_call=model)
        self.assertEqual(row["status"], "PENDING_APPROVAL")

    def test_wrong_code_never_calls_buffer(self):
        with patch.object(content, "Store", return_value=self.store):
            row = content.create_content_preview("movement", chat_id=1, model_call=self.model)
            with patch.object(content.buffer_publisher, "create_post") as publish:
                with self.assertRaisesRegex(ValueError, "code"):
                    content.execute(row["action_id"], "WRONG")
        publish.assert_not_called()

    def test_explicit_approval_publishes_draft_and_persists_receipt(self):
        with patch.object(content, "Store", return_value=self.store):
            row = content.create_content_preview("movement", chat_id=1, model_call=self.model)
            with patch.object(content.buffer_publisher, "resolve_channel", return_value="CH-1"), patch.object(
                content.buffer_publisher, "create_post", return_value={"id": "POST-1", "status": "draft"}
            ) as publish:
                receipt = content.execute(row["action_id"], row["approval_code"])
        self.assertEqual(receipt["post_id"], "POST-1")
        self.assertEqual(self.state["action_queue"][0]["status"], "EXECUTED")
        self.assertTrue(publish.call_args.kwargs["draft"])

    def test_status_reports_buffer_configuration(self):
        with patch.object(content, "Store", return_value=self.store), patch.dict(
            os.environ, {"BUFFER_API_KEY": "configured"}, clear=False
        ):
            self.assertIn("configured", content.status_text())


if __name__ == "__main__":
    unittest.main()

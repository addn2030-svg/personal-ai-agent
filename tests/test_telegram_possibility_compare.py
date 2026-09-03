import os
import unittest
from unittest.mock import Mock, patch

from connectors import telegram_bot as bot


class TelegramPossibilityCompareTests(unittest.TestCase):
    def message(self):
        return {
            "text": "/possibility_compare قارن بين الإطلاق والتجربة المحدودة",
            "message_id": 44,
            "chat": {"id": 9, "type": "private"},
        }

    def test_disabled_compare_has_no_capture_model_or_sheet_write(self):
        message = self.message()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(
            bot, "_local_capture"
        ) as capture, patch.object(
            bot, "_save_intake"
        ) as save, patch.object(
            bot, "api"
        ), patch.object(
            bot, "send"
        ) as send, patch(
            "connectors.super_manager.lean._bedrock_manager"
        ) as model, patch(
            "connectors.possibility_sheet_shadow.append_proposal"
        ) as append:
            bot.handle_message(message)

        capture.assert_not_called()
        save.assert_not_called()
        model.assert_not_called()
        append.assert_not_called()
        self.assertTrue(any("غير مفعّل" in str(call.args[1]) for call in send.call_args_list))

    def test_enabled_compare_calls_two_reasoning_paths_and_never_persists(self):
        message = self.message()
        context = Mock(text="verified evidence", sources=("state",))
        preview = Mock(external_effects=False, persistence="NOT_WRITTEN")

        def model(prompt, **_kwargs):
            if prompt == "CANDIDATE_PROMPT":
                return ("candidate json", "bedrock", "candidate-model", {})
            return ("baseline answer", "bedrock", "baseline-model", {})

        def generate(goal, evidence, generate_fn):
            self.assertIn("قارن", goal)
            self.assertEqual(evidence, context.text)
            self.assertEqual(generate_fn("CANDIDATE_PROMPT"), "candidate json")
            return preview

        with patch.dict(
            os.environ, {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(
            bot, "_local_capture"
        ) as capture, patch.object(
            bot, "_save_intake"
        ) as save, patch.object(
            bot, "api"
        ), patch.object(
            bot, "send"
        ) as send, patch(
            "connectors.super_manager.build_context", return_value=context
        ), patch(
            "connectors.super_manager.build_prompt", return_value="BASELINE_PROMPT"
        ) as build_prompt, patch(
            "connectors.super_manager.lean._bedrock_manager", side_effect=model
        ) as model_call, patch(
            "connectors.strategic_shadow_generator.generate_preview", side_effect=generate
        ), patch(
            "connectors.strategic_shadow_generator.preview_text",
            return_value="STRATEGIC SHADOW PREVIEW — NOT WRITTEN",
        ), patch(
            "connectors.possibility_sheet_shadow.append_proposal"
        ) as append:
            bot.handle_message(message)

        capture.assert_not_called()
        save.assert_not_called()
        append.assert_not_called()
        self.assertEqual(model_call.call_count, 2)
        self.assertFalse(build_prompt.call_args.kwargs["include_strategic"])
        sent = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertIn("CURRENT MANAGER", sent)
        self.assertIn("STRATEGIC PREVIEW", sent)
        self.assertIn("NOT SAVED", sent)
        self.assertIn("NOT WRITTEN", sent)


if __name__ == "__main__":
    unittest.main()

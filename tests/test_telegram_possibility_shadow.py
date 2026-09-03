import os
import unittest
from unittest.mock import Mock, patch

from connectors import telegram_bot as bot


class TelegramPossibilityShadowTests(unittest.TestCase):
    def _base_patches(self):
        message = {
            "text": "/possibility_shadow قارن بين الإطلاق والتجربة المحدودة",
            "chat": {"id": 9, "type": "private"},
        }
        return message

    def test_disabled_command_calls_no_model_and_writes_nothing(self):
        message = self._base_patches()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(
            bot, "_local_capture", return_value="I-SHADOW-1"
        ), patch.object(
            bot, "_save_intake"
        ), patch.object(
            bot, "api"
        ), patch.object(
            bot, "send"
        ) as send, patch.object(
            bot._strategic_shadow, "generate_preview"
        ) as generate, patch.object(
            bot._strategic_shadow.possibility_sheet_shadow, "append_proposal"
        ) as append:
            bot.handle_message(message)

        generate.assert_not_called()
        append.assert_not_called()
        self.assertTrue(any("غير مفعّل" in str(call.args[1]) for call in send.call_args_list))

    def test_enabled_command_returns_preview_without_sheet_persistence(self):
        message = self._base_patches()
        context = Mock(text="verified shadow evidence")
        preview = Mock(external_effects=False, persistence="NOT_WRITTEN")
        with patch.dict(
            os.environ, {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(
            bot, "_local_capture", return_value="I-SHADOW-2"
        ), patch.object(
            bot, "_save_intake"
        ), patch.object(
            bot, "api"
        ), patch.object(
            bot, "send"
        ) as send, patch.object(
            bot._super_manager, "build_context", return_value=context
        ), patch.object(
            bot._strategic_shadow, "generate_preview", return_value=preview
        ) as generate, patch.object(
            bot._strategic_shadow, "preview_text",
            return_value="STRATEGIC SHADOW PREVIEW — NOT WRITTEN",
        ), patch.object(
            bot._strategic_shadow.possibility_sheet_shadow, "append_proposal"
        ) as append:
            bot.handle_message(message)

        generate.assert_called_once()
        self.assertIn(
            "قارن بين الإطلاق والتجربة المحدودة",
            generate.call_args.args[0],
        )
        append.assert_not_called()
        self.assertTrue(any("NOT WRITTEN" in str(call.args[1]) for call in send.call_args_list))


if __name__ == "__main__":
    unittest.main()

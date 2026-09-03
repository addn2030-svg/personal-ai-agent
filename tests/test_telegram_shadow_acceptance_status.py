import os
import unittest
from unittest.mock import patch

from connectors import telegram_bot as bot


class TelegramShadowAcceptanceStatusTests(unittest.TestCase):
    def message(self):
        return {
            "text": "/shadow_acceptance_status",
            "message_id": 45,
            "chat": {"id": 9, "type": "private"},
        }

    def test_disabled_status_reads_nothing_and_persists_nothing(self):
        message = self.message()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(bot, "_local_capture") as capture, patch.object(
            bot, "_save_intake"
        ) as save, patch.object(bot, "api"), patch.object(
            bot, "send"
        ) as send, patch(
            "connectors.shadow_acceptance_sheet.read_acceptance_report"
        ) as read, patch(
            "connectors.shadow_acceptance_sheet.append_review"
        ) as write:
            bot.handle_message(message)

        capture.assert_not_called()
        save.assert_not_called()
        read.assert_not_called()
        write.assert_not_called()
        self.assertTrue(any("غير مفعّل" in str(call.args[1]) for call in send.call_args_list))

    def test_enabled_status_is_read_only_and_formats_blocked_gate(self):
        message = self.message()
        report = {
            "decision": "BLOCKED_CONTINUE_SHADOW",
            "reviewed_runs": 0,
            "domains": [],
            "unsafe_runs": 0,
            "schema_failures": 0,
            "candidate_preferred_rate": 0,
            "candidate_not_worse_rate": 0,
            "gates": {
                "minimum_reviewed_runs": False,
                "minimum_domains": False,
                "zero_unsafe_runs": True,
                "zero_schema_failures": True,
            },
        }
        with patch.dict(
            os.environ, {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(bot, "_local_capture") as capture, patch.object(
            bot, "_save_intake"
        ) as save, patch.object(bot, "api"), patch.object(
            bot, "send"
        ) as send, patch(
            "connectors.shadow_acceptance_sheet.read_acceptance_report",
            return_value=report,
        ) as read, patch(
            "connectors.shadow_acceptance_sheet.append_review"
        ) as write:
            bot.handle_message(message)

        capture.assert_not_called()
        save.assert_not_called()
        read.assert_called_once_with()
        write.assert_not_called()
        sent = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertIn("READ ONLY / NOT SAVED", sent)
        self.assertIn("BLOCKED_CONTINUE_SHADOW", sent)
        self.assertIn("Human-reviewed runs: 0/10", sent)
        self.assertIn("Automatic activation: NO", sent)


if __name__ == "__main__":
    unittest.main()

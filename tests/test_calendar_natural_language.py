import datetime as dt
import unittest
from unittest.mock import patch

from connectors import calendar_actions
from connectors import telegram_bot


class CalendarNaturalLanguageTests(unittest.TestCase):
    def test_relative_english_reminder_parses(self):
        base = dt.datetime(2026, 8, 28, 23, 5, tzinfo=calendar_actions.TZ)
        proposal = calendar_actions.parse_event_request("Remind me in 10 minutes to meditate", base=base)
        self.assertEqual(proposal["start"], base + dt.timedelta(minutes=10))
        self.assertEqual(proposal["title"].lower(), "meditate")
        self.assertEqual(proposal["reminder_minutes"], 0)

    def test_english_natural_language_routes_to_calendar_preview(self):
        message = {"text": "Remind me tomorrow at 9:30 am to call Ahmed", "chat": {"id": 1, "type": "private"}, "message_id": 10}
        with patch.object(telegram_bot, "_authorized", return_value=True), patch.object(
            telegram_bot, "_message_payload", return_value=(message["text"], "TEXT", "")
        ), patch.object(telegram_bot, "_local_capture", return_value="x"), patch.object(
            telegram_bot, "command_remind"
        ) as remind, patch.object(telegram_bot, "_save_intake"):
            telegram_bot.handle_message(message)
        remind.assert_called_once()


if __name__ == "__main__":
    unittest.main()

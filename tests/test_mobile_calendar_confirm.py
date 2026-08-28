import unittest
from unittest.mock import Mock, patch

from connectors.mobile_calendar_confirm import install


class FakeBot:
    def __init__(self):
        self._PENDING_CALENDAR_EVENTS = {}
        self.send = Mock()
        self.command_confirm_event = Mock()


class MobileCalendarConfirmTests(unittest.TestCase):
    def test_empty_token_confirms_unique_pending_event(self):
        bot = FakeBot()
        original = bot.command_confirm_event
        bot._PENDING_CALENDAR_EVENTS["abc123"] = {
            "chat_id": "7", "expires": 2000,
        }
        install(bot)
        with patch("connectors.mobile_calendar_confirm.time.time", return_value=1000):
            bot.command_confirm_event(7, "")
        original.assert_called_once_with(7, "abc123")

    def test_empty_token_refuses_ambiguous_pending_events(self):
        bot = FakeBot()
        original = bot.command_confirm_event
        bot._PENDING_CALENDAR_EVENTS.update({
            "a": {"chat_id": "7", "expires": 2000},
            "b": {"chat_id": "7", "expires": 2000},
        })
        install(bot)
        with patch("connectors.mobile_calendar_confirm.time.time", return_value=1000):
            bot.command_confirm_event(7, "")
        original.assert_not_called()
        self.assertTrue(bot.send.called)

    def test_supplied_token_keeps_existing_confirmation_path(self):
        bot = FakeBot()
        original = bot.command_confirm_event
        install(bot)
        bot.command_confirm_event(7, "xyz789")
        original.assert_called_once_with(7, "xyz789")


if __name__ == "__main__":
    unittest.main()

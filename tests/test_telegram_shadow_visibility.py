import json
import os
import unittest
from unittest.mock import patch

from connectors import telegram_bot as bot


SHADOW_COMMANDS = {
    "possibility_shadow",
    "possibility_compare",
    "shadow_acceptance_status",
}


class TelegramShadowVisibilityTests(unittest.TestCase):
    def test_start_help_hides_shadow_commands_when_flag_off(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            bot, "send"
        ) as send:
            bot.command_start(9)
        output = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertNotIn("possibility_shadow", output)
        self.assertNotIn("possibility_compare", output)
        self.assertNotIn("shadow_acceptance_status", output)

    def test_start_help_shows_shadow_commands_only_when_flag_on(self):
        with patch.dict(
            os.environ, {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ), patch.object(bot, "send") as send:
            bot.command_start(9)
        output = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertIn("Strategic Shadow", output)
        self.assertIn("possibility_compare", output)

    def _configured_menu(self, enabled):
        env = {"AI_STRATEGIC_CREATOR_ENABLED": "1"} if enabled else {}
        calls = []

        def api(method, payload=None, **_kwargs):
            calls.append((method, payload or {}))
            if method == "getMyCommands":
                return []
            return {}

        with patch.dict(os.environ, env, clear=True), patch.object(
            bot, "api", side_effect=api
        ):
            bot.configure_commands()

        payloads = [
            payload for method, payload in calls
            if method == "setMyCommands"
        ]
        self.assertGreaterEqual(len(payloads), 2)
        return {
            item["command"]
            for item in json.loads(payloads[-1]["commands"])
        }

    def test_command_menu_has_zero_shadow_entries_when_off(self):
        commands = self._configured_menu(False)
        self.assertTrue(SHADOW_COMMANDS.isdisjoint(commands))

    def test_command_menu_adds_shadow_entries_when_on(self):
        commands = self._configured_menu(True)
        self.assertTrue(SHADOW_COMMANDS.issubset(commands))


if __name__ == "__main__":
    unittest.main()

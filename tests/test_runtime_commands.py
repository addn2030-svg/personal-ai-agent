import unittest
from unittest.mock import patch

from connectors import runtime_commands


class FakeBot:
    def __init__(self, authorized=True):
        self.authorized = authorized
        self.sent = []
        self.delegated = 0
        self._AI_OS_RUNTIME_COMMANDS = False

        def handle(message):
            self.delegated += 1
        self.handle_message = handle

    def _authorized(self, chat_id, chat_type):
        return self.authorized

    def _clinical_hint(self, text):
        return "patient" in text.lower()

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class RuntimeCommandsTests(unittest.TestCase):
    def test_unauthorized_custom_command_is_dropped_not_delegated(self):
        bot = FakeBot(authorized=False)
        runtime_commands.install(bot)
        bot.handle_message({"chat": {"id": 7, "type": "private"}, "text": "/agents"})
        self.assertEqual(bot.delegated, 0)
        self.assertEqual(bot.sent, [])

    def test_non_custom_message_still_delegates(self):
        bot = FakeBot(authorized=True)
        runtime_commands.install(bot)
        bot.handle_message({"chat": {"id": 7, "type": "private"}, "text": "/help"})
        self.assertEqual(bot.delegated, 1)

    def test_clinical_council_request_is_blocked_before_fanout(self):
        bot = FakeBot(authorized=True)
        runtime_commands.install(bot)
        bot.handle_message({"chat": {"id": 7, "type": "private"}, "text": "/council patient diagnosis"})
        self.assertTrue(any("الحساس" in text for _, text in bot.sent))

    def test_modeltest_uses_redacted_probe_result(self):
        bot = FakeBot(authorized=True)
        runtime_commands.install(bot)
        fake = {
            "openrouter": {"ok": True, "model": "anthropic/claude-sonnet-4.6", "latency_ms": 10},
            "bedrock": {"ok": True, "model": "us.anthropic.claude-sonnet-4-6", "latency_ms": 20},
            "policy": {
                "general_primary": "openrouter",
                "clinical_primary": "bedrock",
                "openrouter_to_bedrock_fallback": True,
            },
        }
        with patch("connectors.model_gateway.live_probe", return_value=fake):
            bot.handle_message({"chat": {"id": 7, "type": "private"}, "text": "/modeltest"})
        text = "\n".join(value for _, value in bot.sent)
        self.assertIn("OpenRouter", text)
        self.assertIn("Bedrock", text)
        self.assertIn("general=openrouter", text)


if __name__ == "__main__":
    unittest.main()

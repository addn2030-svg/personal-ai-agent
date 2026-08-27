import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from connectors import telegram_webhook as webhook


class StagingModeTests(unittest.TestCase):
    def test_disabled_telegram_does_not_call_telegram_api(self):
        with patch.object(webhook, "TELEGRAM_DISABLED", True), \
             patch.object(webhook.bot, "api") as api, \
             patch.object(webhook.bot, "configure_commands") as configure:
            webhook._configure_webhook()
        api.assert_not_called()
        configure.assert_not_called()
        with patch.object(webhook, "TELEGRAM_DISABLED", True):
            self.assertEqual(webhook._telegram_mode(), "disabled")

    def test_startup_probe_runs_once_when_enabled(self):
        result = {
            "openrouter": {"configured": True, "ok": True},
            "bedrock": {"configured": True, "ok": True},
        }
        with patch.object(webhook, "STARTUP_MODEL_PROBE", True), \
             patch.object(webhook.model_gateway, "live_probe", return_value=result) as probe:
            output = io.StringIO()
            with redirect_stdout(output):
                webhook._startup_model_probe()
        probe.assert_called_once_with()
        self.assertIn("Startup model probe:", output.getvalue())

    def test_startup_probe_is_noop_by_default(self):
        with patch.object(webhook, "STARTUP_MODEL_PROBE", False), \
             patch.object(webhook.model_gateway, "live_probe") as probe:
            webhook._startup_model_probe()
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()

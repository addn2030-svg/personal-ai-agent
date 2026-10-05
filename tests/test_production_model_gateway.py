import json
import unittest
from unittest.mock import Mock, patch

from connectors import model_gateway as gateway


class OmniRouteGatewayTests(unittest.TestCase):
    def test_provider_is_always_omniroute(self):
        self.assertEqual(gateway.desired_provider(False), "omniroute")
        self.assertEqual(gateway.desired_provider(True), "omniroute")

    def test_config_requires_base_key_and_model(self):
        with patch.object(gateway, "OMNIROUTE_BASE_URL", "http://localhost:20128"), \
             patch.object(gateway, "OMNIROUTE_API_KEY", "secret"), \
             patch.object(gateway, "OMNIROUTE_MODEL", "catalog/model"):
            self.assertTrue(gateway.configured())
        with patch.object(gateway, "OMNIROUTE_API_KEY", ""):
            self.assertFalse(gateway.configured())

    def test_base_url_adds_v1_once(self):
        with patch.object(gateway, "OMNIROUTE_BASE_URL", "http://gateway.local"):
            self.assertEqual(gateway.base_url(), "http://gateway.local/v1")
        with patch.object(gateway, "OMNIROUTE_BASE_URL", "http://gateway.local/v1/"):
            self.assertEqual(gateway.base_url(), "http://gateway.local/v1")


    def test_chat_request_uses_configured_omniroute_bearer_and_model(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({
            "model": "catalog/model", "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }).encode()
        with patch.object(gateway, "OMNIROUTE_BASE_URL", "http://gateway.local"), \
             patch.object(gateway, "OMNIROUTE_API_KEY", "test-secret"), \
             patch.object(gateway, "OMNIROUTE_MODEL", "catalog/model"), \
             patch("connectors.model_gateway.urllib.request.urlopen", return_value=response) as send:
            answer, usage, _latency = gateway.openrouter_chat(
                model="catalog/model", messages=[{"role": "user", "content": "test"}]
            )
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "http://gateway.local/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(json.loads(request.data)["model"], "catalog/model")
        self.assertEqual(answer, "OK")
        self.assertEqual(usage["inputTokens"], 2)

if __name__ == "__main__":
    unittest.main()

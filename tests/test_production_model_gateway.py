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


class BedrockBackendTests(unittest.TestCase):
    def _bedrock_env(self, **extra):
        values = {"AI_BACKEND": "bedrock", "AWS_REGION": "us-east-1",
                  "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                  "AWS_BEARER_TOKEN": "bedrock-key", "AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "",
                  "BEDROCK_MANAGER_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                  "BEDROCK_CRITIC_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0"}
        values.update(extra)
        return patch.multiple(gateway, **values)

    def test_default_backend_is_omniroute(self):
        with patch.object(gateway, "AI_BACKEND", "omniroute"):
            self.assertFalse(gateway.bedrock_enabled())
            self.assertEqual(gateway.desired_provider(), "omniroute")

    def test_bedrock_configured_requires_region_model_and_auth(self):
        with self._bedrock_env():
            self.assertTrue(gateway.bedrock_configured())
            self.assertEqual(gateway.desired_provider(), "bedrock")
        with self._bedrock_env(AWS_BEARER_TOKEN=""):
            self.assertFalse(gateway.bedrock_configured())
        with self._bedrock_env(AWS_BEARER_TOKEN="", AWS_ACCESS_KEY_ID="AKIA", AWS_SECRET_ACCESS_KEY="s"):
            self.assertTrue(gateway.bedrock_configured())

    def test_payload_splits_system_and_merges_turns(self):
        system, turns = gateway._bedrock_payload([
            {"role": "system", "content": "be brief"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ], {"type": "json_object"})
        self.assertIn("be brief", system[0]["text"])
        self.assertIn("JSON", system[0]["text"])
        self.assertEqual([t["role"] for t in turns], ["user", "assistant", "user"])
        self.assertEqual(turns[-1]["content"][0]["text"], "a\n\nb")

    def test_openrouter_chat_routes_to_bedrock_converse(self):
        client = Mock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": "OK"}]}},
            "usage": {"inputTokens": 3, "outputTokens": 1}}
        with self._bedrock_env(), patch.object(gateway, "_bedrock_client", return_value=client):
            answer, usage, _latency = gateway.openrouter_chat(
                model="catalog/model", messages=[{"role": "system", "content": "s"},
                                                 {"role": "user", "content": "test"}])
        kwargs = client.converse.call_args.kwargs
        self.assertEqual(kwargs["modelId"], "anthropic.claude-3-5-sonnet-20241022-v2:0")
        self.assertEqual(kwargs["system"], [{"text": "s"}])
        self.assertEqual(kwargs["messages"][0]["content"][0]["text"], "test")
        self.assertEqual(answer, "OK")
        self.assertEqual(usage["inputTokens"], 3)
        self.assertEqual(gateway.last_route()["provider"], "bedrock")

    def test_bedrock_failure_falls_back_to_omniroute_when_configured(self):
        client = Mock()
        client.converse.side_effect = RuntimeError("AccessDeniedException")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({
            "model": "catalog/model", "choices": [{"message": {"content": "fallback"}}], "usage": {}}).encode()
        with self._bedrock_env(OMNIROUTE_BASE_URL="http://gateway.local", OMNIROUTE_API_KEY="k",
                               OMNIROUTE_MODEL="catalog/model", BEDROCK_FALLBACK_OMNIROUTE=True), \
             patch.object(gateway, "_bedrock_client", return_value=client), \
             patch("connectors.model_gateway.urllib.request.urlopen", return_value=response):
            answer, _usage, _latency = gateway.openrouter_chat(
                model="catalog/model", messages=[{"role": "user", "content": "test"}])
        self.assertEqual(answer, "fallback")
        route = gateway.last_route()
        self.assertEqual(route["provider"], "omniroute")
        self.assertTrue(route["fallback"])

    def test_bedrock_failure_raises_when_fallback_disabled(self):
        client = Mock()
        client.converse.side_effect = RuntimeError("ThrottlingException")
        with self._bedrock_env(OMNIROUTE_BASE_URL="http://gateway.local", OMNIROUTE_API_KEY="k",
                               OMNIROUTE_MODEL="catalog/model", BEDROCK_FALLBACK_OMNIROUTE=False), \
             patch.object(gateway, "_bedrock_client", return_value=client):
            with self.assertRaises(RuntimeError) as ctx:
                gateway.openrouter_chat(model="x", messages=[{"role": "user", "content": "t"}])
        self.assertIn("Bedrock error", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()

import io
import json
import unittest
from unittest.mock import patch

from connectors import model_router


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ModelRouterTests(unittest.TestCase):
    def test_role_model_is_explicit(self):
        with patch.dict(model_router.ROLE_MODELS, {"manager": "openai/test", "architect": "anthropic/test", "research": "google/test", "fast": "openrouter/auto", "judge": "openai/test"}, clear=True):
            self.assertEqual(model_router.model_for("manager"), "openai/test")
            self.assertEqual(model_router.model_for("architect"), "anthropic/test")
            self.assertEqual(model_router.model_for("research"), "google/test")
            with self.assertRaises(ValueError):
                model_router.model_for("unknown")

    def test_chat_records_requested_and_resolved_model(self):
        payload = {
            "id": "gen-123",
            "model": "anthropic/actual-model",
            "provider": "provider-x",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
        with patch.object(model_router, "OPENROUTER_API_KEY", "test-key"), patch.dict(
            model_router.ROLE_MODELS, {**model_router.ROLE_MODELS, "architect": "anthropic/requested-model"}
        ), patch("urllib.request.urlopen", return_value=_Response(payload)) as mocked:
            result = model_router.chat("architect", "review this")

        self.assertEqual(result.text, "ok")
        self.assertEqual(result.requested_model, "anthropic/requested-model")
        self.assertEqual(result.resolved_model, "anthropic/actual-model")
        self.assertEqual(result.provider, "provider-x")
        request = mocked.call_args.args[0]
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["model"], "anthropic/requested-model")
        self.assertEqual(sent["messages"][-1]["content"], "review this")

    def test_missing_key_fails_closed(self):
        with patch.object(model_router, "OPENROUTER_API_KEY", ""):
            with self.assertRaises(RuntimeError):
                model_router.chat("manager", "hello")


if __name__ == "__main__":
    unittest.main()

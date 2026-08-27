import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))


class ProductionModelGatewayTests(unittest.TestCase):
    def _reload(self, **env):
        with patch.dict(os.environ, env, clear=False):
            import connectors.model_gateway as mg
            return importlib.reload(mg)

    def test_clinical_goes_directly_to_bedrock(self):
        mg = self._reload(
            OPENROUTER_API_KEY="test-key",
            AI_MODEL_PROVIDER="auto",
            AI_CLINICAL_PROVIDER="bedrock",
            OPENROUTER_FALLBACK_BEDROCK="1",
        )
        fallback = Mock(return_value=("bedrock-ok", {"inputTokens": 1}, 5, []))
        with patch.object(mg, "openrouter_chat") as openrouter:
            result = mg.ask(
                1,
                "clinical patient question",
                system_prompt="system",
                sensitive=True,
                bedrock_fallback=fallback,
            )
        self.assertEqual(result[0], "bedrock-ok")
        fallback.assert_called_once()
        openrouter.assert_not_called()
        self.assertEqual(mg.last_route()["provider"], "bedrock")

    def test_openrouter_failure_falls_back_to_bedrock(self):
        mg = self._reload(
            OPENROUTER_API_KEY="test-key",
            AI_MODEL_PROVIDER="auto",
            AI_CLINICAL_PROVIDER="bedrock",
            OPENROUTER_FALLBACK_BEDROCK="1",
        )
        fallback = Mock(return_value=("fallback-ok", {"inputTokens": 1}, 7, []))
        with patch("agent_runtime.build_context", return_value=("ctx", [])), \
             patch.object(mg, "_openai_messages", return_value=[]), \
             patch.object(mg, "openrouter_chat", side_effect=RuntimeError("HTTP 402")):
            result = mg.ask(
                1,
                "general question",
                system_prompt="system",
                sensitive=False,
                bedrock_fallback=fallback,
            )
        self.assertEqual(result[0], "fallback-ok")
        fallback.assert_called_once()
        route = mg.last_route()
        self.assertEqual(route["provider"], "bedrock")
        self.assertTrue(route["fallback"])

    def test_openrouter_is_primary_when_key_exists(self):
        mg = self._reload(
            OPENROUTER_API_KEY="test-key",
            AI_MODEL_PROVIDER="auto",
            AI_CLINICAL_PROVIDER="bedrock",
        )
        self.assertEqual(mg.desired_provider(False), "openrouter")
        self.assertEqual(mg.desired_provider(True), "bedrock")


if __name__ == "__main__":
    unittest.main()

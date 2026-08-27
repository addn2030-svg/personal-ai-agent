import importlib
import os
import unittest
from unittest.mock import patch


class ModelReadinessTests(unittest.TestCase):
    def _reload(self, **env):
        with patch.dict(os.environ, env, clear=False):
            import connectors.model_gateway as mg
            return importlib.reload(mg)

    def test_openrouter_probe_reports_success_without_exposing_key(self):
        mg = self._reload(OPENROUTER_API_KEY="sk-or-super-secret")
        with patch.object(
            mg,
            "openrouter_chat",
            return_value=("OK", {"inputTokens": 1, "outputTokens": 1}, 12),
        ), patch.object(mg, "last_route", return_value={"model": "anthropic/claude-sonnet-4.6"}):
            result = mg.probe_openrouter()
        self.assertTrue(result["ok"])
        self.assertEqual(result["latency_ms"], 12)
        self.assertNotIn("sk-or-super-secret", str(result))

    def test_probe_error_redacts_openrouter_secret(self):
        mg = self._reload(OPENROUTER_API_KEY="sk-or-private")
        with patch.object(mg, "openrouter_chat", side_effect=RuntimeError("bad sk-or-private token")):
            result = mg.probe_openrouter()
        self.assertFalse(result["ok"])
        self.assertNotIn("sk-or-private", result["detail"])
        self.assertIn("[REDACTED]", result["detail"])

    def test_bedrock_config_status_requires_auth(self):
        with patch.dict(
            os.environ,
            {
                "AWS_BEARER_TOKEN_BEDROCK": "",
                "AWS_ACCESS_KEY_ID": "",
                "AWS_SECRET_ACCESS_KEY": "",
                "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            },
            clear=False,
        ):
            import connectors.model_gateway as mg
            mg = importlib.reload(mg)
            self.assertFalse(mg.bedrock_configured())


if __name__ == "__main__":
    unittest.main()

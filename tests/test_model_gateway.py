import importlib
import os
import unittest
from unittest.mock import patch


class ModelGatewayTests(unittest.TestCase):
    def _reload(self, **env):
        with patch.dict(os.environ, env, clear=False):
            import connectors.model_gateway as mg
            return importlib.reload(mg)

    def test_one_openrouter_key_enables_multi_model_roles(self):
        mg = self._reload(OPENROUTER_API_KEY="sk-or-test", AI_MODEL_PROVIDER="auto")
        self.assertTrue(mg.configured())
        self.assertEqual(mg.desired_provider(False), "openrouter")
        models = mg.models_for_roles()
        self.assertTrue(models["manager"].startswith("anthropic/"))
        self.assertTrue(models["critic"].startswith("openai/"))
        self.assertTrue(models["google"].startswith("google/"))

    def test_clinical_defaults_to_bedrock(self):
        mg = self._reload(
            OPENROUTER_API_KEY="sk-or-test",
            AI_MODEL_PROVIDER="openrouter",
            AI_CLINICAL_PROVIDER="bedrock",
        )
        self.assertEqual(mg.desired_provider(True), "bedrock")

    def test_sensitive_openrouter_policy_forces_zdr_and_denies_collection(self):
        mg = self._reload(OPENROUTER_API_KEY="sk-or-test")
        policy = mg._provider_policy(True)
        self.assertTrue(policy["zdr"])
        self.assertEqual(policy["data_collection"], "deny")


if __name__ == "__main__":
    unittest.main()

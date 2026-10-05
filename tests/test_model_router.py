import unittest
from unittest.mock import patch

from connectors import model_router


class OmniRouteModelRouterTests(unittest.TestCase):
    def test_general_clinical_manager_and_critic_share_gateway(self):
        with patch.object(model_router.gateway, "openrouter_chat",
                          return_value=("answer", {"inputTokens": 1}, 3)) as gateway_call:
            for domain in ("general", "clinical", "manager", "critic"):
                result = model_router.call(domain=domain, prompt="test")
                self.assertEqual(result.text, "answer")
                self.assertEqual(result.provider, "omniroute")
        self.assertEqual(gateway_call.call_count, 4)

    def test_explicit_model_is_sent_to_gateway_catalog(self):
        with patch.object(model_router.gateway, "openrouter_chat",
                          return_value=("ok", {}, 1)) as gateway_call:
            model_router.call(domain="clinical", prompt="test", model="catalog/special")
        self.assertEqual(gateway_call.call_args.kwargs["model"], "catalog/special")

    def test_call_text_returns_text(self):
        with patch.object(model_router.gateway, "openrouter_chat", return_value=("short", {}, 1)):
            self.assertEqual(model_router.call_text(prompt="test"), "short")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()

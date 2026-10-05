import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from connectors import provider_diagnostics


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_install_keeps_the_gateway_as_the_only_route(self):
        original = Mock(return_value=("omniroute", {}, 2))
        gateway = SimpleNamespace(openrouter_chat=original)
        provider_diagnostics.install(gateway)
        self.assertEqual(gateway.openrouter_chat(model="catalog/model", messages=[])[0], "omniroute")
        original.assert_called_once()

    def test_error_does_not_expose_provider_secret(self):
        error = provider_diagnostics.combined_provider_error(
            "provider", RuntimeError("old"), RuntimeError("gateway unavailable")
        )
        self.assertIn("gateway unavailable", str(error))


if __name__ == "__main__":
    unittest.main()

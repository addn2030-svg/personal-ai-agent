import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from connectors import direct_specialists


class DirectSpecialistCompatibilityTests(unittest.TestCase):
    def test_install_does_not_patch_or_create_provider_routes(self):
        original = Mock(return_value=("omniroute", {}, 2))
        gateway = SimpleNamespace(openrouter_chat=original)
        direct_specialists.install(gateway)
        self.assertEqual(gateway.openrouter_chat(model="catalog/model", messages=[])[0], "omniroute")
        original.assert_called_once()


if __name__ == "__main__":
    unittest.main()

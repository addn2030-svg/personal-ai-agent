import unittest
from unittest.mock import patch

from connectors import bedrock_team
from connectors.model_router import RouterResponse


class OmniRouteTeamTests(unittest.TestCase):
    def test_team_call_uses_router_and_returns_omniroute_result(self):
        result = RouterResponse("PACKET", "catalog/manager", {"outputTokens": 2}, 4, "omniroute")
        with patch("connectors.model_router.call", return_value=result) as call:
            actual = bedrock_team.converse_text(
                model_id="catalog/manager", system="system", prompt="task", role="manager"
            )
        self.assertEqual(actual.text, "PACKET")
        self.assertEqual(actual.provider, "omniroute")
        call.assert_called_once()

    def test_configuration_comes_from_omniroute(self):
        with patch.object(bedrock_team.models, "configured", return_value=True):
            self.assertTrue(bedrock_team.configured())


if __name__ == "__main__":
    unittest.main()

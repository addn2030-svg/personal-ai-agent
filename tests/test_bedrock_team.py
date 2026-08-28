import unittest
from unittest.mock import Mock, patch

from connectors import bedrock_team


class BedrockTeamTests(unittest.TestCase):
    def test_converse_text_is_compact_and_explicit(self):
        client = Mock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": "PACKET"}]}},
            "usage": {"inputTokens": 25, "outputTokens": 7},
        }
        with patch.object(bedrock_team, "configured", return_value=True), patch.object(
            bedrock_team, "_client", return_value=client
        ):
            result = bedrock_team.converse_text(
                model_id="global.openai.gpt-5.6-luna",
                system="short system",
                prompt="exact packet",
                max_tokens=100,
                role="test",
            )

        self.assertEqual(result.text, "PACKET")
        self.assertEqual(result.model, "global.openai.gpt-5.6-luna")
        self.assertEqual(result.usage["outputTokens"], 7)
        kwargs = client.converse.call_args.kwargs
        self.assertEqual(kwargs["messages"][0]["content"][0]["text"], "exact packet")
        self.assertEqual(kwargs["system"][0]["text"], "short system")
        self.assertEqual(kwargs["inferenceConfig"]["maxTokens"], 100)
        self.assertEqual(kwargs["requestMetadata"]["workload"], "test")

    def test_converse_requires_bedrock_configuration(self):
        with patch.object(bedrock_team, "configured", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Bedrock"):
                bedrock_team.converse_text(
                    model_id="global.openai.gpt-5.6-luna",
                    system="",
                    prompt="x",
                )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock, patch

from connectors import bedrock_team


class BedrockTeamTests(unittest.TestCase):
    def test_default_lean_model_is_nova_micro(self):
        self.assertEqual(bedrock_team.BEDROCK_LEAN_MODEL_ID, "amazon.nova-micro-v1:0")

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
                model_id="amazon.nova-micro-v1:0",
                system="short system",
                prompt="exact packet",
                max_tokens=100,
                role="test",
            )

        self.assertEqual(result.text, "PACKET")
        self.assertEqual(result.model, "amazon.nova-micro-v1:0")
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
                    model_id="amazon.nova-micro-v1:0",
                    system="",
                    prompt="x",
                )

    def test_lean_specialist_stays_inside_bedrock_for_model_fallback(self):
        calls = []

        def fake(*, model_id, **kwargs):
            calls.append(model_id)
            if model_id == "global.openai.gpt-5.6-luna":
                raise RuntimeError("AccessDeniedException")
            return bedrock_team.BedrockTeamResult(
                text="PACKET", model=model_id, usage={}, latency_ms=4,
            )

        with patch.object(bedrock_team, "BEDROCK_LEAN_MODEL_ID", "global.openai.gpt-5.6-luna"), patch.object(
            bedrock_team, "BEDROCK_LEAN_FALLBACK_MODEL_ID", "amazon.nova-micro-v1:0"
        ), patch.object(bedrock_team, "converse_text", side_effect=fake):
            result = bedrock_team.lean_specialist("x")

        self.assertEqual(calls, ["global.openai.gpt-5.6-luna", "amazon.nova-micro-v1:0"])
        self.assertEqual(result.model, "amazon.nova-micro-v1:0")

    def test_probe_checks_manager_and_lean_model_with_tiny_calls(self):
        def fake(*, model_id, system, prompt, max_tokens, temperature, role):
            self.assertEqual(prompt, "OK")
            self.assertEqual(max_tokens, 16)
            return bedrock_team.BedrockTeamResult(
                text="OK", model=model_id,
                usage={"inputTokens": 3, "outputTokens": 1}, latency_ms=5,
            )

        with patch.object(bedrock_team, "configured", return_value=True), patch.object(
            bedrock_team, "converse_text", side_effect=fake
        ):
            result = bedrock_team.probe()

        self.assertTrue(result["manager"]["ok"])
        self.assertTrue(result["lean"]["ok"])
        self.assertEqual(result["lean"]["model"], bedrock_team.BEDROCK_LEAN_MODEL_ID)

    def test_probe_returns_safe_lean_error_without_raising(self):
        def fake(*, model_id, **kwargs):
            if model_id == bedrock_team.BEDROCK_LEAN_MODEL_ID:
                raise RuntimeError("AccessDeniedException: model unavailable")
            return bedrock_team.BedrockTeamResult(
                text="OK", model=model_id, usage={}, latency_ms=4,
            )

        with patch.object(bedrock_team, "configured", return_value=True), patch.object(
            bedrock_team, "converse_text", side_effect=fake
        ):
            result = bedrock_team.probe()

        self.assertTrue(result["manager"]["ok"])
        self.assertFalse(result["lean"]["ok"])
        self.assertIn("AccessDeniedException", result["lean"]["error"])


if __name__ == "__main__":
    unittest.main()

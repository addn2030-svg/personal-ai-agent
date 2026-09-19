# -*- coding: utf-8 -*-
"""Tests for the unified model_router and its Bedrock-primary policy."""
import unittest
from unittest.mock import Mock, patch

from connectors import model_router


class ModelRouterTests(unittest.TestCase):
    @staticmethod
    def _bedrock_client(answer="bedrock answer"):
        client = Mock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": answer}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }
        return client

    def test_general_domain_defaults_to_bedrock_without_openrouter(self):
        """Ordinary requests must not require OPENROUTER_API_KEY."""
        client = self._bedrock_client("Claude answer")
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "bedrock"), \
             patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router.gateway, "openrouter_chat") as openrouter, \
             patch.object(model_router, "_bedrock_client", return_value=client):
            response = model_router.call(
                domain="general",
                prompt="هل العمل في الليل يؤثر على العضلات؟",
                model="anthropic/claude-sonnet-4.6",
            )

        self.assertEqual(response.text, "Claude answer")
        self.assertEqual(response.provider, "bedrock")
        self.assertEqual(response.model, "us.anthropic.claude-sonnet-4-6")
        openrouter.assert_not_called()
        self.assertEqual(client.converse.call_args.kwargs["modelId"], "us.anthropic.claude-sonnet-4-6")

    def test_clinical_domain_routes_to_bedrock(self):
        """domain='clinical' should go directly to Bedrock."""
        mock_client = self._bedrock_client("clinical answer")
        with patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router, "_bedrock_client", return_value=mock_client):
            response = model_router.call(
                domain="clinical",
                prompt="راجع حالة المريض",
                model="us.anthropic.claude-sonnet-4-6",
            )
            self.assertEqual(response.text, "clinical answer")
            self.assertEqual(response.provider, "bedrock")
            mock_client.converse.assert_called_once()

    def test_explicit_openrouter_opt_in_still_works(self):
        mock_answer = "Executive brief content"
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "openrouter"), \
             patch.object(model_router.gateway, "openrouter_chat", return_value=(mock_answer, {"inputTokens": 10}, 100)) as chat, \
             patch.object(model_router.gateway, "last_route", return_value={"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"}):
            response = model_router.call(
                domain="general",
                prompt="أنشئ ملخص تنفيذي",
                model="anthropic/claude-sonnet-4.6",
            )
        self.assertEqual(response.text, mock_answer)
        self.assertEqual(response.provider, "openrouter")
        self.assertEqual(str(response), mock_answer)
        chat.assert_called_once()

    def test_call_text_convenience_returns_string(self):
        mock_answer = "brief"
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "openrouter"), \
             patch.object(model_router.gateway, "openrouter_chat", return_value=(mock_answer, {}, 10)), \
             patch.object(model_router.gateway, "last_route", return_value={"provider": "openrouter", "model": "test"}):
            result = model_router.call_text(
                domain="general",
                prompt="test",
                model="anthropic/claude-sonnet-4.6",
            )
            self.assertEqual(result, "brief")
            self.assertIsInstance(result, str)

    def test_general_fallback_to_bedrock_when_explicit_openrouter_fails(self):
        mock_client = self._bedrock_client("fallback answer")
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "openrouter"), \
             patch.object(model_router.gateway, "openrouter_chat", side_effect=RuntimeError("OpenRouter down")), \
             patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router.gateway, "OPENROUTER_FALLBACK_BEDROCK", True), \
             patch.object(model_router, "_bedrock_client", return_value=mock_client):
            response = model_router.call(
                domain="general",
                prompt="test fallback",
                model="anthropic/claude-sonnet-4.6",
            )
            self.assertEqual(response.text, "fallback answer")
            self.assertEqual(response.provider, "bedrock")

    def test_reported_arabic_health_question_is_clinical(self):
        from connectors import capability_truth

        self.assertTrue(capability_truth.clinical_private("هل العمل في الليل يؤثر على العضلات"))


if __name__ == "__main__":
    unittest.main()

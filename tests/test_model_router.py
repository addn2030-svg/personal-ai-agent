# -*- coding: utf-8 -*-
"""Tests for the unified model_router — الصحيح vs الخطأ."""
import os
import unittest
from unittest.mock import Mock, patch

from connectors import model_router


class ModelRouterTests(unittest.TestCase):
    def test_general_domain_routes_to_openrouter_automatically(self):
        """الصحيح: domain='general' يوجه تلقائياً إلى OpenRouter."""
        mock_answer = "Executive brief content"
        with patch.object(model_router.gateway, "openrouter_chat", return_value=(mock_answer, {"inputTokens": 10}, 100)) as chat, \
             patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router.gateway, "last_route", return_value={"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"}):
            brief_prompt = "أنشئ ملخص تنفيذي"
            response = model_router.call(
                domain="general",
                prompt=brief_prompt,
                model=os.getenv("AI_MODEL_MANAGER", "anthropic/claude-sonnet-4.6"),
            )
            # response should be RouterResponse with text
            self.assertEqual(response.text, mock_answer)
            self.assertEqual(response.provider, "openrouter")
            self.assertEqual(str(response), mock_answer)
            chat.assert_called_once()
            # Ensure model used is from AI_MODEL_MANAGER env or default
            called_model = chat.call_args.kwargs.get("model") or chat.call_args[1].get("model") if len(chat.call_args) > 1 else chat.call_args.kwargs.get("model")
            # The model param should be passed through
            self.assertIn("claude", chat.call_args.kwargs["model"].lower() if "model" in chat.call_args.kwargs else mock_answer)

    def test_clinical_domain_routes_to_bedrock(self):
        """domain='clinical' should go directly to Bedrock."""
        mock_client = Mock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "clinical answer"}]}},
            "usage": {"inputTokens": 5, "outputTokens": 5},
        }
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

    def test_call_text_convenience_returns_string(self):
        mock_answer = "brief"
        with patch.object(model_router.gateway, "openrouter_chat", return_value=(mock_answer, {}, 10)), \
             patch.object(model_router.gateway, "last_route", return_value={"provider": "openrouter", "model": "test"}):
            result = model_router.call_text(
                domain="general",
                prompt="test",
                model="anthropic/claude-sonnet-4.6",
            )
            self.assertEqual(result, "brief")
            self.assertIsInstance(result, str)

    def test_general_fallback_to_bedrock_when_openrouter_fails(self):
        mock_client = Mock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "fallback answer"}]}},
            "usage": {},
        }
        with patch.object(model_router.gateway, "openrouter_chat", side_effect=RuntimeError("OpenRouter down")), \
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

    def test_example_from_user_request(self):
        """Example from the user prompt should work."""
        mock_answer = "ملخص تنفيذي"
        with patch.object(model_router.gateway, "openrouter_chat", return_value=(mock_answer, {}, 5)), \
             patch.object(model_router.gateway, "last_route", return_value={"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"}):
            brief_prompt = "أنشئ ملخص"
            response = model_router.call(
                domain="general",  # يوجه تلقائياً إلى OpenRouter
                prompt=brief_prompt,
                model=os.getenv("AI_MODEL_MANAGER", "anthropic/claude-sonnet-4.6"),
            )
            self.assertEqual(response.text, "ملخص تنفيذي")


if __name__ == "__main__":
    unittest.main()

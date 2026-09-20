# -*- coding: utf-8 -*-
"""Tests for the unified model_router and its Gemini-primary policy."""
import unittest
from unittest.mock import patch

from connectors import model_router


class ModelRouterTests(unittest.TestCase):
    def test_general_domain_defaults_to_gemini_without_other_provider(self):
        """Ordinary requests must use Gemini API without Bedrock/OpenRouter."""
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "gemini"), \
             patch.object(model_router.gateway, "GEMINI_API_KEY", "test-key"), \
             patch.object(model_router.gateway, "gemini_configured", return_value=True), \
             patch.object(model_router.gateway, "openrouter_chat") as openrouter, \
             patch.object(model_router, "_gemini_converse", return_value=model_router.RouterResponse(
                 text="Gemini answer", model="gemini-3.7-flash", usage={}, latency_ms=7,
                 provider="gemini",
             )) as gemini:
            response = model_router.call(
                domain="general",
                prompt="هل العمل في الليل يؤثر على العضلات؟",
                model="anthropic/claude-sonnet-4.6",
            )

        self.assertEqual(response.text, "Gemini answer")
        self.assertEqual(response.provider, "gemini")
        gemini.assert_called_once()
        openrouter.assert_not_called()

    def test_clinical_domain_routes_to_gemini(self):
        with patch.object(model_router.gateway, "AI_CLINICAL_PROVIDER", "gemini"), \
             patch.object(model_router.gateway, "GEMINI_API_KEY", "test-key"), \
             patch.object(model_router.gateway, "gemini_configured", return_value=True), \
             patch.object(model_router, "_gemini_converse", return_value=model_router.RouterResponse(
                 text="clinical Gemini answer", model="gemini-3.7-flash", usage={}, latency_ms=5,
                 provider="gemini",
             )) as gemini:
            response = model_router.call(
                domain="clinical",
                prompt="راجع الحالة الصحية",
                model="google/gemini-3.7-flash",
            )
        self.assertEqual(response.text, "clinical Gemini answer")
        self.assertEqual(response.provider, "gemini")
        gemini.assert_called_once()

    def test_gemini_direct_adapter_is_used(self):
        with patch.object(model_router.gateway, "GEMINI_API_KEY", "test-key"), \
             patch.object(model_router.gateway, "gemini_configured", return_value=True), \
             patch("connectors.direct_specialists._direct_gemini", return_value=(
                 "direct Gemini", {"inputTokens": 2}, 9, "gemini-3.7-flash"
             )) as direct:
            response = model_router.call(domain="general", prompt="test")
        self.assertEqual(response.text, "direct Gemini")
        self.assertEqual(response.provider, "gemini")
        direct.assert_called_once()

    def test_explicit_openrouter_compatibility_route_still_works(self):
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
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "openrouter"), \
             patch.object(model_router.gateway, "openrouter_chat", side_effect=RuntimeError("OpenRouter down")), \
             patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router.gateway, "OPENROUTER_FALLBACK_BEDROCK", True), \
             patch.object(model_router, "_bedrock_converse", return_value=model_router.RouterResponse(
                 text="fallback answer", model="bedrock-model", usage={}, latency_ms=2,
                 provider="bedrock", fallback=True,
             )) as bedrock:
            response = model_router.call(
                domain="general",
                prompt="test fallback",
                model="anthropic/claude-sonnet-4.6",
            )
        self.assertEqual(response.text, "fallback answer")
        self.assertEqual(response.provider, "bedrock")
        bedrock.assert_called_once()

    def test_explicit_bedrock_compatibility_route_still_works(self):
        with patch.object(model_router.gateway, "bedrock_configured", return_value=True), \
             patch.object(model_router, "_bedrock_client") as client:
            client.return_value.converse.return_value = {
                "output": {"message": {"content": [{"text": "bedrock compatibility"}]}},
                "usage": {},
            }
            response = model_router.call(
                domain="bedrock",
                prompt="compatibility test",
                model="us.anthropic.claude-sonnet-4-6",
            )
        self.assertEqual(response.text, "bedrock compatibility")
        self.assertEqual(response.provider, "bedrock")

    def test_kimi_provider_uses_kimi_converse(self):
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "kimi"), \
             patch.object(model_router.gateway, "kimi_configured", return_value=True), \
             patch.object(model_router.gateway, "KIMI_MODEL", "kimi-k2.5"), \
             patch.object(model_router.gateway, "kimi_model_id", return_value="kimi-k2.5"), \
             patch.object(model_router, "_gemini_converse") as gemini, \
             patch.object(model_router, "_kimi_converse", return_value=model_router.RouterResponse(
                 text="Kimi answer", model="kimi-k2.5", usage={}, latency_ms=11,
                 provider="kimi",
             )) as kimi:
            response = model_router.call(domain="general", prompt="hello")
        self.assertEqual(response.text, "Kimi answer")
        self.assertEqual(response.provider, "kimi")
        kimi.assert_called_once()
        gemini.assert_not_called()

    def test_gemini_quota_overflows_to_kimi_for_general(self):
        with patch.object(model_router.gateway, "AI_MODEL_PROVIDER", "gemini"), \
             patch.object(model_router.gateway, "GEMINI_FALLBACK_KIMI", True), \
             patch.object(model_router.gateway, "kimi_configured", return_value=True), \
             patch.object(model_router.gateway, "KIMI_MODEL", "kimi-k2.5"), \
             patch.object(model_router.gateway, "is_quota_error", return_value=True), \
             patch.object(model_router, "_gemini_converse", side_effect=RuntimeError("HTTP 429 quota")), \
             patch.object(model_router, "_kimi_converse", return_value=model_router.RouterResponse(
                 text="overflow", model="kimi-k2.5", usage={}, latency_ms=9,
                 provider="kimi", fallback=True,
             )) as kimi:
            response = model_router.call(domain="general", prompt="continue after 20")
        self.assertEqual(response.text, "overflow")
        self.assertEqual(response.provider, "kimi")
        self.assertTrue(response.fallback)
        kimi.assert_called_once()

    def test_clinical_does_not_overflow_to_kimi(self):
        with patch.object(model_router.gateway, "AI_CLINICAL_PROVIDER", "gemini"), \
             patch.object(model_router.gateway, "GEMINI_FALLBACK_KIMI", True), \
             patch.object(model_router.gateway, "kimi_configured", return_value=True), \
             patch.object(model_router, "_gemini_converse", side_effect=RuntimeError("HTTP 429 quota")), \
             patch.object(model_router, "_kimi_converse") as kimi:
            with self.assertRaisesRegex(RuntimeError, "429"):
                model_router.call(domain="clinical", prompt="ألم في الركبة", sensitive=True)
        kimi.assert_not_called()

    def test_reported_arabic_health_question_is_clinical(self):
        from connectors import capability_truth

        self.assertTrue(capability_truth.clinical_private("هل العمل في الليل يؤثر على العضلات"))


if __name__ == "__main__":
    unittest.main()

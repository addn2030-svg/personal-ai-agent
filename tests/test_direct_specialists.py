import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from connectors import direct_specialists as direct


class DirectSpecialistRoutingTests(unittest.TestCase):
    def _gateway(self, *, configured=True):
        original = Mock(return_value=("router answer", {}, 5))
        routes = []
        gateway = SimpleNamespace(
            openrouter_chat=original,
            _safe_error=lambda exc: str(exc),
            _set_route=lambda provider, model, fallback=False: routes.append((provider, model, fallback)),
            configured=lambda: configured,
            _direct_specialists_installed=False,
        )
        return gateway, original, routes

    def test_openai_model_prefers_direct_api(self):
        gateway, original, routes = self._gateway()
        with patch.object(direct, "OPENAI_API_KEY", "test-key"), patch.object(
            direct, "_direct_openai", return_value=("gpt direct", {"outputTokens": 3}, 8, "gpt-5.6-sol")
        ):
            direct.install(gateway)
            answer, usage, latency = gateway.openrouter_chat(
                model="openai/gpt-5.6-sol",
                messages=[{"role": "user", "content": "review"}],
            )
        self.assertEqual(answer, "gpt direct")
        self.assertEqual(usage["outputTokens"], 3)
        self.assertEqual(latency, 8)
        self.assertEqual(routes[-1][0], "openai")
        original.assert_not_called()

    def test_gemini_model_prefers_direct_api(self):
        gateway, original, routes = self._gateway()
        with patch.object(direct, "GEMINI_API_KEY", "test-key"), patch.object(
            direct, "_direct_gemini", return_value=("gemini direct", {}, 7, "gemini-3.7-flash")
        ):
            direct.install(gateway)
            answer, _usage, _latency = gateway.openrouter_chat(
                model="google/gemini-3.7-flash",
                messages=[{"role": "user", "content": "research"}],
            )
        self.assertEqual(answer, "gemini direct")
        self.assertEqual(routes[-1][0], "gemini")
        original.assert_not_called()

    def test_gemini_interactions_failure_uses_generate_content_directly(self):
        messages = [{"role": "user", "content": "research"}]
        with patch.object(direct, "GEMINI_API_KEY", "test-key"), patch.object(
            direct, "_direct_gemini_interactions", side_effect=RuntimeError("interaction unavailable")
        ) as interactions, patch.object(
            direct,
            "_direct_gemini_generate_content",
            return_value=("generate direct", {"outputTokens": 4}, 9, "gemini-3.7-flash"),
        ) as generate:
            result = direct._direct_gemini(
                model="google/gemini-3.7-flash", messages=messages, max_tokens=500
            )
        self.assertEqual(result[0], "generate direct")
        interactions.assert_called_once()
        generate.assert_called_once()

    def test_sensitive_call_never_uses_direct_specialist_api(self):
        gateway, original, _routes = self._gateway()
        with patch.object(direct, "OPENAI_API_KEY", "test-key"), patch.object(
            direct, "_direct_openai"
        ) as direct_call:
            direct.install(gateway)
            result = gateway.openrouter_chat(
                model="openai/gpt-5.6-sol",
                messages=[{"role": "user", "content": "private"}],
                sensitive=True,
            )
        self.assertEqual(result[0], "router answer")
        direct_call.assert_not_called()
        original.assert_called_once()

    def test_direct_failure_falls_back_to_openrouter(self):
        gateway, original, _routes = self._gateway(configured=True)
        with patch.object(direct, "GEMINI_API_KEY", "test-key"), patch.object(
            direct, "_direct_gemini", side_effect=RuntimeError("quota")
        ):
            direct.install(gateway)
            result = gateway.openrouter_chat(
                model="google/gemini-3.7-flash",
                messages=[{"role": "user", "content": "research"}],
            )
        self.assertEqual(result[0], "router answer")
        original.assert_called_once()

    def test_direct_failure_raises_when_no_openrouter_fallback(self):
        gateway, original, _routes = self._gateway(configured=False)
        with patch.object(direct, "OPENAI_API_KEY", "test-key"), patch.object(
            direct, "_direct_openai", side_effect=RuntimeError("direct unavailable")
        ):
            direct.install(gateway)
            with self.assertRaisesRegex(RuntimeError, "direct unavailable"):
                gateway.openrouter_chat(
                    model="openai/gpt-5.6-sol",
                    messages=[{"role": "user", "content": "review"}],
                )
        original.assert_not_called()

    def test_non_specialist_model_keeps_existing_router(self):
        gateway, original, _routes = self._gateway()
        direct.install(gateway)
        result = gateway.openrouter_chat(
            model="anthropic/claude-sonnet-4.6",
            messages=[{"role": "user", "content": "manage"}],
        )
        self.assertEqual(result[0], "router answer")
        original.assert_called_once()


if __name__ == "__main__":
    unittest.main()

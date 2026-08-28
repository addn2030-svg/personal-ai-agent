import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from connectors import provider_diagnostics as diag


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_gemini_success_uses_direct_probe(self):
        gateway = SimpleNamespace(openrouter_chat=Mock(), _set_route=Mock())
        with patch.object(diag, "GEMINI_API_KEY", "key"), patch.object(
            diag.direct, "_direct_gemini", return_value=("ok", {}, 4, "gemini-3.7-flash")
        ):
            diag.install(gateway)
            answer, _usage, _latency = gateway.openrouter_chat(
                model="google/gemini-3.7-flash", messages=[{"role":"user","content":"x"}]
            )
        self.assertEqual(answer, "ok")
        gateway._set_route.assert_called_with("gemini", "gemini-3.7-flash")

    def test_combines_direct_and_fallback_errors(self):
        original = Mock(side_effect=RuntimeError("OpenRouter HTTP 402 credits"))
        gateway = SimpleNamespace(openrouter_chat=original, _set_route=Mock())
        with patch.object(diag, "GEMINI_API_KEY", "key"), patch.object(
            diag.direct, "_direct_gemini", side_effect=RuntimeError("HTTP 403 API key denied")
        ):
            diag.install(gateway)
            with self.assertRaisesRegex(RuntimeError, "Gemini direct failed: HTTP 403 API key denied"):
                gateway.openrouter_chat(
                    model="google/gemini-3.7-flash", messages=[{"role":"user","content":"x"}]
                )


if __name__ == "__main__":
    unittest.main()

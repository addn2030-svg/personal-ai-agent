# -*- coding: utf-8 -*-
"""Kimi / Moonshot overflow provider."""
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from connectors import model_gateway as gateway


class KimiProviderTests(unittest.TestCase):
    def test_kimi_model_id_strips_prefixes(self):
        self.assertEqual(gateway.kimi_model_id("moonshotai/kimi-k2.5"), "kimi-k2.5")
        self.assertEqual(gateway.kimi_model_id("kimi/kimi-k3"), "kimi-k3")
        self.assertEqual(gateway.kimi_model_id("kimi-k2.5"), "kimi-k2.5")

    def test_quota_error_detection(self):
        self.assertTrue(gateway.is_quota_error(RuntimeError("HTTP 429: RESOURCE_EXHAUSTED quota")))
        self.assertTrue(gateway.is_quota_error(RuntimeError("You exceeded your current quota")))
        self.assertTrue(gateway.is_quota_error(RuntimeError(
            'Gemini direct APIs failed: interactions=HTTP 429: '
            '{"error":{"message":"Rate limit exceeded for model gemini-3.7-flash '
            '(limit: 20 requests per day on Free Tier). Please retry in 39s"}}'
        )))
        self.assertFalse(gateway.is_quota_error(RuntimeError("HTTP 401 invalid api key")))

    def test_desired_provider_kimi(self):
        with patch.object(gateway, "AI_MODEL_PROVIDER", "kimi"), \
             patch.object(gateway, "AI_CLINICAL_PROVIDER", "gemini"):
            self.assertEqual(gateway.desired_provider(False), "kimi")
            self.assertEqual(gateway.desired_provider(True), "gemini")

    def test_kimi_chat_posts_openai_compatible_payload(self):
        payload = {
            "choices": [{"message": {"content": "OK"}}],
            "model": "kimi-k2.5",
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }
        captured = {}

        class FakeResponse:
            def read(self):
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=90):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse()

        with patch.object(gateway, "KIMI_API_KEY", "sk-secret-kimi"), \
             patch.object(gateway, "KIMI_BASE_URL", "https://api.moonshot.ai/v1"), \
             patch.object(gateway, "KIMI_MODEL", "kimi-k2.5"), \
             patch.object(gateway, "kimi_configured", return_value=True), \
             patch("urllib.request.urlopen", fake_urlopen):
            answer, usage, latency = gateway.kimi_chat(
                model="kimi-k2.5",
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=16,
                temperature=0,
            )
        self.assertEqual(answer, "OK")
        self.assertEqual(usage["inputTokens"], 3)
        self.assertGreaterEqual(latency, 0)
        self.assertEqual(captured["url"], "https://api.moonshot.ai/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "kimi-k2.5")
        auth = captured["headers"].get("Authorization") or captured["headers"].get("authorization")
        self.assertEqual(auth, "Bearer sk-secret-kimi")
        self.assertEqual(gateway.last_route()["provider"], "kimi")

    def test_kimi_http_error_redacts_key(self):
        err = HTTPError(
            "https://api.moonshot.ai/v1/chat/completions",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"bad sk-secret-kimi"}'),
        )
        with patch.object(gateway, "KIMI_API_KEY", "sk-secret-kimi"), \
             patch.object(gateway, "kimi_configured", return_value=True), \
             patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as raised:
                gateway.kimi_chat(model="kimi-k2.5", messages=[{"role": "user", "content": "x"}])
            self.assertIn("Kimi HTTP 401", str(raised.exception))
            safe = gateway._safe_error(RuntimeError("failed sk-secret-kimi"))
            self.assertNotIn("sk-secret-kimi", safe)
            self.assertIn("[REDACTED]", safe)

    def test_status_includes_kimi_fields(self):
        status = gateway.status()
        self.assertIn("kimi_configured", status)
        self.assertIn("kimi_model", status)
        self.assertIn("gemini_fallback_kimi", status)


if __name__ == "__main__":
    unittest.main()

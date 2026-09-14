# -*- coding: utf-8 -*-
"""A dead Telegram link must degrade the bot, not crash-loop the deploy.

The outage this covers: `setWebhook` raised during startup, the exception left
`run()`, and the container restarted forever — the bot was silent and the only
evidence was a stack trace nobody was watching. Registration is now retried in
the background while the HTTP server keeps answering, and /health vs /ready
separate "process alive" from "Telegram delivery actually registered".
"""
import json
import socket
import sys
import threading
import time
import unittest
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

from connectors import telegram_webhook as webhook  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, dict]:
    """Return (status, body) — /ready uses 503 as a signal, so do not raise on it."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class ConfigureWebhookTests(unittest.TestCase):
    def test_missing_token_is_reported_not_raised(self):
        with patch.object(webhook.bot, "TOKEN", ""):
            self.assertFalse(webhook._configure_webhook())
        state = webhook.webhook_state()
        self.assertFalse(state["registered"])
        self.assertIn("TELEGRAM_BOT_TOKEN", state["error"])

    def test_missing_public_url_is_reported_not_raised(self):
        with patch.object(webhook.bot, "TOKEN", "123:abc"), \
             patch.object(webhook, "WEBHOOK_SECRET", "secret-abc"), \
             patch.object(webhook, "PUBLIC_BASE_URL", ""):
            self.assertFalse(webhook._configure_webhook())
        self.assertIn("public URL", webhook.webhook_state()["error"])

    def test_transient_telegram_failure_recovers_on_retry(self):
        calls = {"n": 0}

        def flaky(method, payload=None, timeout=30):
            calls["n"] += 1
            if method == "setWebhook" and calls["n"] < 3:
                raise RuntimeError("telegram 502")
            return {"url": "https://example.com/telegram/webhook", "pending_update_count": 0}

        with patch.object(webhook.bot, "TOKEN", "123:abc"), \
             patch.object(webhook, "WEBHOOK_SECRET", "secret-abc"), \
             patch.object(webhook, "PUBLIC_BASE_URL", "https://example.com"), \
             patch.object(webhook.bot, "api", side_effect=flaky), \
             patch.object(webhook.bot, "configure_commands"), \
             patch.object(webhook.time, "sleep"):
            self.assertTrue(webhook._configure_webhook())
        # three attempts: two 502s on setWebhook, then setWebhook + getWebhookInfo
        self.assertEqual(webhook.webhook_state()["attempts"], 3)
        self.assertEqual(calls["n"], 4)
        self.assertTrue(webhook.webhook_state()["registered"])

    def test_permanent_failure_returns_false_and_records_the_reason(self):
        with patch.object(webhook.bot, "TOKEN", "123:abc"), \
             patch.object(webhook, "WEBHOOK_SECRET", "secret-abc"), \
             patch.object(webhook, "PUBLIC_BASE_URL", "https://example.com"), \
             patch.object(webhook.bot, "api", side_effect=RuntimeError("telegram unreachable")), \
             patch.object(webhook.bot, "configure_commands"), \
             patch.object(webhook.time, "sleep"):
            self.assertFalse(webhook._configure_webhook())
        state = webhook.webhook_state()
        self.assertFalse(state["registered"])
        self.assertIn("telegram unreachable", state["error"])
        self.assertEqual(state["attempts"], len(webhook.WEBHOOK_SETUP_BACKOFF_SECONDS))

    def test_registrar_keeps_retrying_until_it_succeeds(self):
        attempts = []

        def configure():
            attempts.append(1)
            return len(attempts) >= 3

        stop = threading.Event()
        with patch.object(webhook, "_configure_webhook", side_effect=configure):
            worker = threading.Thread(
                target=webhook._webhook_registrar, kwargs={"stop_event": stop, "interval": 0.01}
            )
            worker.start()
            deadline = time.time() + 10
            while len(attempts) < 3 and time.time() < deadline:
                time.sleep(0.01)
            worker.join(timeout=5)
        self.assertGreaterEqual(len(attempts), 3)
        self.assertFalse(worker.is_alive())


class ServerSurvivesTelegramOutageTests(unittest.TestCase):
    """End-to-end: start the real run() with Telegram unreachable."""

    @contextmanager
    def _serve(self, *, api_side_effect):
        port = _free_port()
        captured = {}

        class _CapturingServer(webhook.ThreadingHTTPServer):
            def serve_forever(self, *args, **kwargs):
                captured["server"] = self
                super().serve_forever(*args, **kwargs)

        thread = threading.Thread(target=webhook.run, daemon=True)
        with patch.object(webhook, "PORT", port), \
             patch.object(webhook, "ThreadingHTTPServer", _CapturingServer), \
             patch.object(webhook.bot, "TOKEN", "123:abc"), \
             patch.object(webhook, "WEBHOOK_SECRET", "secret-abc"), \
             patch.object(webhook, "PUBLIC_BASE_URL", "https://example.com"), \
             patch.object(webhook.bot, "api", side_effect=api_side_effect), \
             patch.object(webhook.bot, "configure_commands"), \
             patch.object(webhook.time, "sleep"), \
             patch.object(webhook, "_probe_sheets", return_value=(True, "sheets ok")), \
             patch.object(webhook, "_start_calendar_alert_worker", return_value=None), \
             patch.object(webhook.manager_fast_canary, "start_if_enabled", return_value=None), \
             patch.object(webhook.proactive_worker, "start_if_enabled", return_value=None), \
             patch.object(webhook, "WEBHOOK_RETRY_INTERVAL_SECONDS", 3600):
            thread.start()
            try:
                deadline = time.time() + 15
                while "server" not in captured and time.time() < deadline:
                    time.sleep(0.02)
                self.assertIn("server", captured)
                # Give the registrar a moment to fail the first attempt.
                deadline = time.time() + 10
                while time.time() < deadline and webhook.webhook_state()["error"] is None:
                    time.sleep(0.02)
                yield port
            finally:
                server = captured.get("server")
                if server is not None:
                    server.shutdown()
                    server.server_close()
                thread.join(timeout=10)

    def test_health_stays_up_and_ready_reports_the_outage(self):
        with self._serve(api_side_effect=RuntimeError("telegram unreachable")) as port:
            status, health = _get(port, "/health")
            self.assertEqual(status, 200)
            self.assertTrue(health["ok"])  # liveness never depends on Telegram
            self.assertFalse(health["webhook_registered"])
            self.assertIn("telegram unreachable", health["webhook_error"])

            status, ready = _get(port, "/ready")
            self.assertEqual(status, 503)
            self.assertFalse(ready["ok"])
            self.assertFalse(ready["webhook_registered"])
            self.assertTrue(ready["sheets_ok"])

    def test_ready_turns_green_once_registration_succeeds(self):
        ok_result = {"url": "https://example.com/telegram/webhook", "pending_update_count": 0}
        with self._serve(api_side_effect=lambda method, payload=None, timeout=30: ok_result) as port:
            deadline = time.time() + 10
            while time.time() < deadline:
                status, ready = _get(port, "/ready")
                if status == 200:
                    break
                time.sleep(0.1)
            self.assertEqual(status, 200)
            self.assertTrue(ready["webhook_registered"])
            self.assertIsNone(ready["webhook_error"])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Safe Railway staging server for Commerce Agent acceptance testing.

This server is used only when AI_OS_DISABLE_TELEGRAM=1. It never configures a
Telegram webhook, never reads delivery/payment secrets, and never performs a
real purchase. It exposes a tiny HTTP surface for staging verification.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# When Railway starts this file by path (python connectors/commerce_staging_server.py),
# Python puts /app/connectors on sys.path rather than the repository root. Add the
# root explicitly before importing the connectors package, matching the production
# runtime's boot behavior.
BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors.commerce_sandbox import render_smoke_test, run_smoke_test

PORT = int(os.environ.get("PORT", "8080") or "8080")


def checkout_link_selftest() -> dict:
    """Verify staging agent -> checkout provider URL/auth without any checkout.

    The request intentionally uses an unsupported action. A correctly wired
    provider must authenticate the shared secret first and then reject the
    action as UNSUPPORTED_ACTION. The provider therefore never reaches the
    browser executor or retailer checkout path.
    """
    url = os.environ.get("COMMERCE_CHECKOUT_WEBHOOK_URL", "").strip()
    secret = os.environ.get("COMMERCE_CHECKOUT_SECRET", "").strip()
    if not url or not secret:
        raise RuntimeError("CHECKOUT_LINK_NOT_CONFIGURED")

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path.rstrip("/") != "/checkout":
        raise RuntimeError("INVALID_CHECKOUT_WEBHOOK_URL")

    payload = {
        "secret": secret,
        "action": "selftest",
        "idempotency_key": "STAGING-CHECKOUT-LINK-SELFTEST",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
        raise RuntimeError("UNEXPECTED_PROVIDER_RESPONSE:" + str(body.get("error") or response.status))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        error = str(body.get("error") or "")
        if exc.code == 422 and error == "UNSUPPORTED_ACTION":
            return {
                "ok": True,
                "test": "checkout_link",
                "provider_reachable": True,
                "provider_auth": True,
                "real_purchase": False,
            }
        if exc.code == 401:
            raise RuntimeError("CHECKOUT_PROVIDER_AUTH_FAILED") from exc
        raise RuntimeError(f"CHECKOUT_PROVIDER_SELFTEST_FAILED:{exc.code}:{error[:120]}") from exc


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in {"/", "/health", "/ready"}:
            payload = {
                "ok": True,
                "environment": "staging",
                "telegram_disabled": True,
                "commerce_mode": "SANDBOX",
                "real_purchase": False,
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if self.path == "/commerce_test":
            try:
                result = run_smoke_test()
                self._send(200, render_smoke_test(result).encode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - staging diagnostic boundary
                self._send(500, f"COMMERCE SANDBOX — FAIL\n{str(exc)[:300]}".encode("utf-8"))
            return
        if self.path == "/checkout_link_test":
            try:
                result = checkout_link_selftest()
                self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            except Exception as exc:  # noqa: BLE001 - staging diagnostic boundary
                payload = {"ok": False, "test": "checkout_link", "error": str(exc)[:240], "real_purchase": False}
                self._send(502, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self._send(404, b"Not found")

    def log_message(self, fmt: str, *args):
        print("commerce-staging:", fmt % args, flush=True)


def run():
    print(
        "Commerce staging server active | Telegram disabled | real_purchase=false",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    run()

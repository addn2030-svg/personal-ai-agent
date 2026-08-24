# -*- coding: utf-8 -*-
"""Minimal Railway Telegram webhook runner for Abdulrahman AI OS.

P0 goals:
- eliminate getUpdates polling conflicts (HTTP 409),
- retry transient Google Sheets writes without adding a new database/queue,
- validate the live Sheets gateway/schema at startup,
- keep the existing bot command/business logic unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from connectors import telegram_bot as bot

PORT = int(os.environ.get("PORT", "8080"))
PUBLIC_BASE_URL = os.environ.get("TELEGRAM_WEBHOOK_BASE_URL", "").strip().rstrip("/")
if not PUBLIC_BASE_URL:
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        PUBLIC_BASE_URL = f"https://{railway_domain}"

WEBHOOK_PATH = os.environ.get("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = "/" + WEBHOOK_PATH

WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
if not WEBHOOK_SECRET and bot.TOKEN:
    WEBHOOK_SECRET = hashlib.sha256((bot.TOKEN + ":webhook").encode("utf-8")).hexdigest()[:48]

_MAX_BODY = 2 * 1024 * 1024
_recent_updates = deque(maxlen=2000)
_recent_lock = threading.Lock()

# Keep the original write implementation, then add bounded retry around it.
_raw_append = bot._append


def _append_with_retry(tab: str, row: list):
    last = None
    for attempt, delay in enumerate((0, 1, 2, 4), start=1):
        if delay:
            time.sleep(delay)
        try:
            return _raw_append(tab, row)
        except Exception as exc:  # noqa: BLE001 - intentional connector boundary
            last = exc
            print(f"Sheets write attempt {attempt}/4 failed for {tab}: {str(exc)[:180]}", flush=True)
    raise RuntimeError(f"Sheets write failed after retry: {last}")


bot._append = _append_with_retry


def _clinical_minimize(text: str):
    """Do not persist free-text clinical details in general Sheets logs.

    Clinical context is used for the live response, but the generic intake/conversation
    tables only retain a marker. This is deliberate data minimization for P0.
    """
    if bot._clinical_hint(text or ""):
        return "[CLINICAL_PRIVATE_REDACTED_AT_SOURCE]"
    return _original_redact(text)


_original_redact = bot._redact
bot._redact = _clinical_minimize


def _probe_sheets():
    """Cheap startup compatibility check for the deployed Apps Script gateway."""
    try:
        from connectors import sheet_intelligence as si

        if not si.configured():
            return False, "Google Sheets not configured"
        sheets = si.metadata()
        titles = {row.get("title") for row in sheets}
        required = {bot.INTAKE_TAB, bot.CONVERSATION_TAB, bot.STATUS_TAB}
        missing = sorted(required - titles)
        if missing:
            return False, "Missing required tabs: " + ", ".join(missing)

        # Probe the exact action that previously failed with 404/old deployment.
        if si.WEBHOOK_URL and si.WEBHOOK_SECRET:
            si._webhook("upsert_metrics", sheet="Executive_Brief", metrics={})
        elif "Executive_Brief" not in titles:
            return False, "Missing Executive_Brief tab"
        return True, "Sheets gateway/schema compatible"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:220]


def _configure_webhook():
    if not bot.TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("No public URL. Set TELEGRAM_WEBHOOK_BASE_URL or RAILWAY_PUBLIC_DOMAIN")
    if not WEBHOOK_SECRET:
        raise RuntimeError("Unable to derive Telegram webhook secret")

    bot.configure_commands()
    webhook_url = PUBLIC_BASE_URL + WEBHOOK_PATH
    bot.api(
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": WEBHOOK_SECRET,
            "allowed_updates": json.dumps(["message"]),
            "drop_pending_updates": "false",
            "max_connections": "10",
        },
        timeout=30,
    )
    info = bot.api("getWebhookInfo", timeout=20)
    print(
        "Telegram webhook active: "
        f"url_set={bool(info.get('url'))} pending={info.get('pending_update_count', 0)}",
        flush=True,
    )


def _already_processed(update_id: int) -> bool:
    with _recent_lock:
        return update_id in _recent_updates


def _mark_processed(update_id: int):
    with _recent_lock:
        _recent_updates.append(update_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "AbdulrahmanAgentWebhook/1.0"

    def log_message(self, fmt, *args):
        print("http:", fmt % args, flush=True)

    def _send_json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            ok, detail = _probe_sheets()
            self._send_json(200 if ok else 503, {"ok": ok, "telegram_mode": "webhook", "sheets": detail})
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        if self.path != WEBHOOK_PATH:
            self._send_json(404, {"ok": False})
            return

        supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not supplied or not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            self._send_json(403, {"ok": False})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._send_json(400, {"ok": False})
            return

        try:
            update = json.loads(self.rfile.read(length).decode("utf-8"))
            update_id = int(update.get("update_id", -1))
            if update_id >= 0 and _already_processed(update_id):
                self._send_json(200, {"ok": True, "duplicate": True})
                return

            message = update.get("message")
            if message:
                bot.handle_message(message)
            if update_id >= 0:
                _mark_processed(update_id)
            self._send_json(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            # Non-2xx tells Telegram to retry delivery; no success is acknowledged here.
            print(f"Telegram webhook processing error: {str(exc)[:300]}", flush=True)
            self._send_json(500, {"ok": False})


def run():
    _configure_webhook()
    sheets_ok, detail = _probe_sheets()
    print(f"Sheets startup check: {'OK' if sheets_ok else 'WARN'} - {detail}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"HTTP webhook server listening on :{PORT}{WEBHOOK_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()

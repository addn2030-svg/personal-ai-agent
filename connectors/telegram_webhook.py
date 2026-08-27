# -*- coding: utf-8 -*-
"""Railway HTTP runner for Telegram webhook + secure external-AI ingestion.

P0 goals:
- eliminate getUpdates polling conflicts (HTTP 409),
- retry transient Google Sheets writes without adding a new database/queue,
- validate the live Sheets gateway/schema at startup,
- keep the existing bot command/business logic unchanged.

v0.5 adds an authenticated /api/ai/update route on the same Railway service.
External advisers enter through Unified Inbox and never write operational state directly.

Staging safety:
- AI_OS_DISABLE_TELEGRAM=1 starts the HTTP/model service without configuring Telegram;
- AI_OS_STARTUP_MODEL_PROBE=1 performs one sanitized live OpenRouter + Bedrock probe at startup.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))

from connectors import ai_gateway, model_gateway
from connectors import telegram_bot as bot
from connectors.brief_runtime import install as install_brief_runtime
from connectors.council_runtime import install as install_council_runtime
from connectors.runtime_commands import install as install_runtime_commands

PORT = int(os.environ.get("PORT", "8080"))
TELEGRAM_DISABLED = os.environ.get("AI_OS_DISABLE_TELEGRAM", "").strip() == "1"
STARTUP_MODEL_PROBE = os.environ.get("AI_OS_STARTUP_MODEL_PROBE", "").strip() == "1"
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
_processing_updates = set()
_recent_lock = threading.Lock()

# Runtime feature wrappers. Security wrapper installs last and becomes outermost.
install_brief_runtime(bot)
install_council_runtime(bot)
install_runtime_commands(bot)

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
    """Do not persist free-text clinical details in general Sheets logs."""
    if bot._clinical_hint(text or ""):
        return "[CLINICAL_PRIVATE_REDACTED_AT_SOURCE]"
    return _original_redact(text)


_original_redact = bot._redact
bot._redact = _clinical_minimize


def _telegram_mode() -> str:
    return "disabled" if TELEGRAM_DISABLED else "webhook"


def _probe_sheets():
    """Cheap compatibility check for the deployed Apps Script gateway and required tabs."""
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

        if si.WEBHOOK_URL and si.WEBHOOK_SECRET:
            si._webhook("upsert_metrics", sheet="Executive_Brief", metrics={})
        elif "Executive_Brief" not in titles:
            return False, "Missing Executive_Brief tab"
        return True, "Sheets gateway/schema compatible"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:220]


def _configure_webhook():
    if TELEGRAM_DISABLED:
        print("Telegram webhook intentionally disabled for this environment", flush=True)
        return
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


def _claim_update(update_id: int) -> bool:
    if update_id < 0:
        return True
    with _recent_lock:
        if update_id in _recent_updates or update_id in _processing_updates:
            return False
        _processing_updates.add(update_id)
        return True


def _complete_update(update_id: int):
    if update_id < 0:
        return
    with _recent_lock:
        _processing_updates.discard(update_id)
        _recent_updates.append(update_id)


def _process_update(update_id: int, message: dict | None):
    try:
        if message:
            bot.handle_message(message)
    except Exception as exc:  # noqa: BLE001
        print(f"Telegram background processing error: {str(exc)[:300]}", flush=True)
        chat_id = ((message or {}).get("chat") or {}).get("id")
        if chat_id is not None:
            try:
                bot.send(chat_id, f"❌ تعذر تنفيذ الطلب: {str(exc)[:180]}")
            except Exception as send_exc:  # noqa: BLE001
                print(f"Telegram error notification failed: {send_exc}", flush=True)
    finally:
        _complete_update(update_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "AbdulrahmanAgentWebhook/1.4"

    def log_message(self, fmt, *args):
        print("http:", fmt % args, flush=True)

    def _send_json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            raise ValueError("invalid request body size")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"ok": True, "telegram_mode": _telegram_mode(), "ai_gateway": "v0.5"})
            return
        if self.path == "/ready":
            ok, detail = _probe_sheets()
            model_status = model_gateway.status()
            self._send_json(
                200 if ok else 503,
                {
                    "ok": ok,
                    "telegram_mode": _telegram_mode(),
                    "sheets": detail,
                    "ai_gateway_sources": ai_gateway.configured_sources(),
                    "models": {
                        "openrouter_configured": model_status["openrouter_configured"],
                        "bedrock_configured": model_status["bedrock_configured"],
                        "general_provider": model_status["desired_general_provider"],
                        "clinical_provider": model_status["desired_clinical_provider"],
                        "roles": model_status["models"],
                        "bedrock_model": model_status["bedrock_model"],
                    },
                },
            )
            return
        if self.path == ai_gateway.HEALTH_PATH:
            self._send_json(200, ai_gateway.health())
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        if self.path == ai_gateway.UPDATE_PATH:
            source = ai_gateway.authenticate(self.headers)
            if not source:
                self._send_json(403, {"ok": False, "error": "AI gateway authentication failed"})
                return
            try:
                result = ai_gateway.ingest(source, self._read_json())
                self._send_json(200 if result.get("duplicate") else 202, result)
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)[:240]})
            except Exception as exc:  # noqa: BLE001
                print(f"AI gateway error: {str(exc)[:300]}", flush=True)
                self._send_json(500, {"ok": False, "error": "AI gateway internal error"})
            return

        if TELEGRAM_DISABLED:
            self._send_json(404, {"ok": False, "telegram_mode": "disabled"})
            return
        if self.path != WEBHOOK_PATH:
            self._send_json(404, {"ok": False})
            return

        supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not supplied or not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            self._send_json(403, {"ok": False})
            return

        try:
            update = self._read_json()
            update_id = int(update.get("update_id", -1))
            if not _claim_update(update_id):
                self._send_json(200, {"ok": True, "duplicate": True})
                return

            message = update.get("message")
            worker = threading.Thread(
                target=_process_update,
                args=(update_id, message),
                name=f"telegram-update-{update_id}",
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"ok": True, "accepted": True})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)[:200]})
        except Exception as exc:  # noqa: BLE001
            print(f"Telegram webhook acceptance error: {str(exc)[:300]}", flush=True)
            self._send_json(500, {"ok": False})


def _startup_model_probe():
    if not STARTUP_MODEL_PROBE:
        return
    try:
        probe = model_gateway.live_probe()
        print("Startup model probe: " + json.dumps(probe, ensure_ascii=False, default=str), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Startup model probe failed safely: {model_gateway._safe_error(exc)}", flush=True)


def run():
    _configure_webhook()
    sheets_ok, detail = _probe_sheets()
    model_status = model_gateway.status()
    print(f"Sheets startup check: {'OK' if sheets_ok else 'WARN'} - {detail}", flush=True)
    print(f"AI gateway sources configured: {', '.join(ai_gateway.configured_sources()) or 'none'}", flush=True)
    print(
        "Model routing: "
        f"general={model_status['desired_general_provider']} "
        f"clinical={model_status['desired_clinical_provider']} "
        f"openrouter={'yes' if model_status['openrouter_configured'] else 'no'} "
        f"bedrock={'yes' if model_status['bedrock_configured'] else 'no'}",
        flush=True,
    )
    _startup_model_probe()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(
        f"HTTP server listening on :{PORT} "
        f"(Telegram {_telegram_mode()}, AI {ai_gateway.UPDATE_PATH})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    run()

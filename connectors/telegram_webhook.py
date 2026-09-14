# -*- coding: utf-8 -*-
"""Minimal Railway Telegram webhook runner for Abdulrahman AI OS.

P0 goals:
- eliminate getUpdates polling conflicts (HTTP 409),
- retry transient Google Sheets writes without adding a new database/queue,
- validate the live Sheets gateway/schema at startup,
- keep the existing bot command/business logic unchanged,
- keep Calendar/Telegram reminders alive while production runs in webhook mode,
- optionally run the FAST-only Manager canary behind an explicit feature flag.
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

from connectors import bridge_api
from connectors import telegram_bot as bot
from connectors import manager_fast_canary
from connectors import proactive_worker
from connectors.brief_runtime import install as install_brief_runtime
from connectors.mobile_calendar_confirm import install as install_mobile_calendar_confirm

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

CALENDAR_ALERT_LOOP_SECONDS = max(15, int(os.environ.get("CALENDAR_ALERT_LOOP_SECONDS", "30")))

# Webhook registration is retried instead of being fatal. A transient Telegram or
# network error used to propagate out of run() and crash-loop the container
# forever, with the bot completely silent and only a stack trace to show for it.
WEBHOOK_SETUP_BACKOFF_SECONDS = (0, 2, 4, 8, 16)
WEBHOOK_RETRY_INTERVAL_SECONDS = max(30, int(os.environ.get("TELEGRAM_WEBHOOK_RETRY_SECONDS", "60")))

_webhook_state = {
    "registered": False,
    "error": None,
    "attempts": 0,
    "url": None,
    "updated_at": None,
}
_webhook_state_lock = threading.Lock()

_MAX_BODY = 2 * 1024 * 1024
_recent_updates = deque(maxlen=2000)
_processing_updates = set()
_recent_lock = threading.Lock()

# Install production behavior patches before any Telegram update is processed.
install_brief_runtime(bot)
install_mobile_calendar_confirm(bot)

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

        # Probe the exact action that previously failed when an old Apps Script deployment was live.
        if si.WEBHOOK_URL and si.WEBHOOK_SECRET:
            si._webhook("upsert_metrics", sheet="Executive_Brief", metrics={})
        elif "Executive_Brief" not in titles:
            return False, "Missing Executive_Brief tab"
        return True, "Sheets gateway/schema compatible"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:220]


def _record_webhook_state(**fields):
    with _webhook_state_lock:
        _webhook_state.update(fields)
        _webhook_state["updated_at"] = time.time()
        return dict(_webhook_state)


def webhook_state() -> dict:
    """Snapshot of webhook registration health (surfaced on /health and /ready)."""
    with _webhook_state_lock:
        return dict(_webhook_state)


def _configure_webhook() -> bool:
    """Register the webhook with Telegram. Returns True on success; never raises.

    A transient Telegram/network failure or a missing env var must not kill the
    process: the HTTP server keeps answering /health, the registrar keeps
    retrying, and /ready reports the exact reason so a watchdog can alert.
    """
    missing = None
    if not bot.TOKEN:
        missing = "TELEGRAM_BOT_TOKEN is not set"
    elif not PUBLIC_BASE_URL:
        missing = "No public URL. Set TELEGRAM_WEBHOOK_BASE_URL or RAILWAY_PUBLIC_DOMAIN"
    elif not WEBHOOK_SECRET:
        missing = "Unable to derive Telegram webhook secret"

    if missing:
        _record_webhook_state(registered=False, error=missing, url=None)
        print(f"Telegram webhook NOT registered: {missing}", flush=True)
        return False

    webhook_url = PUBLIC_BASE_URL + WEBHOOK_PATH
    last_error = None
    for attempt, delay in enumerate(WEBHOOK_SETUP_BACKOFF_SECONDS, start=1):
        if delay:
            time.sleep(delay)
        try:
            bot.configure_commands()
            bot.api(
                "setWebhook",
                {
                    "url": webhook_url,
                    "secret_token": WEBHOOK_SECRET,
                    "allowed_updates": json.dumps(["message", "callback_query"]),
                    "drop_pending_updates": "false",
                    "max_connections": "10",
                },
                timeout=30,
            )
            info = bot.api("getWebhookInfo", timeout=20)
            _record_webhook_state(registered=True, error=None, url=webhook_url, attempts=attempt)
            print(
                "Telegram webhook active: "
                f"url_set={bool(info.get('url'))} pending={info.get('pending_update_count', 0)}",
                flush=True,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - external Telegram boundary
            last_error = exc
            print(
                f"Telegram webhook setup attempt {attempt}/"
                f"{len(WEBHOOK_SETUP_BACKOFF_SECONDS)} failed: {str(exc)[:180]}",
                flush=True,
            )

    _record_webhook_state(registered=False, error=str(last_error)[:300], url=webhook_url,
                          attempts=len(WEBHOOK_SETUP_BACKOFF_SECONDS))
    print(
        "Telegram webhook NOT registered — continuing to serve /health and retrying: "
        f"{str(last_error)[:220]}",
        flush=True,
    )
    return False


def _webhook_registrar(stop_event: threading.Event | None = None,
                       interval: float | None = None) -> None:
    """Keep trying to register the webhook until it sticks. Never exits the process."""
    stop_event = stop_event or threading.Event()
    interval = float(interval if interval is not None else WEBHOOK_RETRY_INTERVAL_SECONDS)
    while not stop_event.is_set():
        if _configure_webhook():
            return
        if stop_event.wait(interval):
            break


def _start_webhook_registrar(interval: float | None = None) -> threading.Thread:
    worker = threading.Thread(
        target=_webhook_registrar,
        kwargs={"interval": interval},
        name="telegram-webhook-registrar",
        daemon=True,
    )
    worker.start()
    return worker


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


def _process_update(update_id: int, message: dict | None, callback_query: dict | None = None):
    """Run slow bot work after Telegram has already received HTTP 200.

    Telegram retries webhooks when a handler takes too long. Commands such as /brief
    can require Google + Bedrock calls, so processing synchronously can duplicate the
    progress message even when update-id de-duplication exists. Acknowledge first,
    process in a daemon thread, and surface failures directly to the owner.
    """
    try:
        if message:
            bot.handle_message(message)
        elif callback_query:
            if hasattr(bot, "handle_callback"):
                bot.handle_callback(callback_query)
    except Exception as exc:  # noqa: BLE001
        print(f"Telegram background processing error: {str(exc)[:300]}", flush=True)
        chat_id = ((message or {}).get("chat") or {}).get("id")
        if chat_id is None and callback_query:
            chat_id = ((callback_query.get("message") or {}).get("chat") or {}).get("id")
        if chat_id is not None:
            try:
                bot.send(chat_id, f"❌ تعذر تنفيذ الطلب: {str(exc)[:180]}")
            except Exception as send_exc:  # noqa: BLE001
                print(f"Telegram error notification failed: {send_exc}", flush=True)
    finally:
        _complete_update(update_id)


def _calendar_alert_worker(stop_event: threading.Event | None = None, sleep_seconds: float | None = None):
    """Keep Telegram appointment reminders active in production webhook mode.

    The existing bot reminder function owns de-duplication and the 60-second Calendar
    read throttle. This worker only gives it a heartbeat while the webhook server is
    running. Calendar API failures are fail-soft and retried on the next heartbeat.
    """
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else CALENDAR_ALERT_LOOP_SECONDS)
    while not stop_event.is_set():
        try:
            bot._maybe_send_calendar_alerts()
        except Exception as exc:  # noqa: BLE001 - external Calendar/Telegram boundary
            print(f"Calendar reminder worker warning: {str(exc)[:220]}", flush=True)
        stop_event.wait(max(0.01, interval))


def _start_calendar_alert_worker():
    worker = threading.Thread(
        target=_calendar_alert_worker,
        name="calendar-reminder-worker",
        daemon=True,
    )
    worker.start()
    return worker


class Handler(BaseHTTPRequestHandler):
    server_version = "AbdulrahmanAgentWebhook/1.5"

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
            # Liveness must not depend on Google or Telegram availability; Railway should
            # not restart a healthy process merely because an external API is degraded.
            # Registration state is reported, never enforced, so a dying webhook shows up
            # in monitoring instead of in a restart loop.
            state = webhook_state()
            self._send_json(
                200,
                {
                    "ok": True,
                    "telegram_mode": "webhook",
                    "webhook_registered": state["registered"],
                    "webhook_error": state["error"],
                    "calendar_reminders": True,
                    "manager_fast_canary": manager_fast_canary.enabled(),
                    "proactive_worker": proactive_worker.enabled(),
                },
            )
            return
        if self.path == "/ready":
            ok, detail = _probe_sheets()
            state = webhook_state()
            # Readiness is the signal a watchdog alerts on: it is 503 until Telegram
            # delivery is actually registered, even though the process is healthy.
            ready = ok and state["registered"]
            self._send_json(
                200 if ready else 503,
                {
                    "ok": ready,
                    "telegram_mode": "webhook",
                    "sheets": detail,
                    "sheets_ok": ok,
                    "webhook_registered": state["registered"],
                    "webhook_error": state["error"],
                    "manager_fast_canary": manager_fast_canary.enabled(),
                    "proactive_worker": proactive_worker.enabled(),
                },
            )
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        if self.path == "/chat":
            # First-party bridge API (see connectors/bridge_api.py).
            bridge_api.handle_chat(self, bot)
            return
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
            if not _claim_update(update_id):
                self._send_json(200, {"ok": True, "duplicate": True})
                return

            message = update.get("message")
            callback_query = update.get("callback_query")
            worker = threading.Thread(
                target=_process_update,
                args=(update_id, message, callback_query),
                name=f"telegram-update-{update_id}",
                daemon=True,
            )
            worker.start()

            # Acknowledge Telegram immediately. Slow Google/Bedrock calls continue in
            # the background and cannot trigger Telegram webhook redelivery.
            self._send_json(200, {"ok": True, "accepted": True})
        except Exception as exc:  # noqa: BLE001
            print(f"Telegram webhook acceptance error: {str(exc)[:300]}", flush=True)
            self._send_json(500, {"ok": False})


def run():
    # Webhook registration runs in the background: a Telegram/network blip must not
    # stop the HTTP server from answering /health, and it must not crash-loop the
    # deploy. The registrar retries until it succeeds and /ready reports the state.
    _start_webhook_registrar()
    sheets_ok, detail = _probe_sheets()
    print(f"Sheets startup check: {'OK' if sheets_ok else 'WARN'} - {detail}", flush=True)
    _start_calendar_alert_worker()
    print(
        f"Calendar reminder worker active: heartbeat={CALENDAR_ALERT_LOOP_SECONDS}s",
        flush=True,
    )
    manager_fast_canary.start_if_enabled()
    proactive_worker.start_if_enabled()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"HTTP webhook server listening on :{PORT}{WEBHOOK_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()

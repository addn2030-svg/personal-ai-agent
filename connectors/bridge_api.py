# -*- coding: utf-8 -*-
"""HTTP bridge API for trusted first-party clients.

Lets companion services (e.g. telegram-agent-bot) call the agent chat
pipeline directly, without Telegram in the middle:

    POST /chat
        Authorization: Bearer <BRIDGE_API_KEY>
        {"messages": [{"role": "user", "content": "..."}],
         "user": {"id": <telegram user id>, "locale": "en"}}

    -> {"ok": true, "reply": "...", "latency_ms": 1234}

Security:
- Disabled (503) until BRIDGE_API_KEY is set in service variables.
- Bearer key compared with hmac.compare_digest.
- Never trusts the caller-supplied text more than a Telegram message:
  it flows through the same redaction/provider policy as normal chat.

Notes:
- chat_id is taken from user.id so per-chat memory and Sheets audit stay
  attached to the real person.
- Prior turns are passed as a compact context prefix (capped) so multi-turn
  companion conversations keep continuity.
"""
from __future__ import annotations

import hmac
import json
import os

BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY", "").strip()
_MAX_BODY = 512 * 1024
_MAX_HISTORY_CHARS = 1500
_MAX_HISTORY_TURNS = 6


def _bearer_ok(handler) -> bool:
    if not BRIDGE_API_KEY:
        return False
    supplied = handler.headers.get("Authorization", "")
    if not supplied.startswith("Bearer "):
        return False
    return hmac.compare_digest(supplied[len("Bearer "):].strip(), BRIDGE_API_KEY)


def _compose_text(messages: list) -> str:
    user_text = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("content", "")).strip():
            user_text = str(m["content"]).strip()
            break
    if not user_text:
        return ""
    prior = [m for m in messages[:-1] if isinstance(m, dict) and str(m.get("content", "")).strip()]
    if not prior:
        return user_text
    lines = [f"{str(m.get('role', 'user')).lower()}: {str(m['content']).strip()}" for m in prior[-_MAX_HISTORY_TURNS:]]
    block = "\n".join(lines)[-_MAX_HISTORY_CHARS:]
    return f"[bridge conversation so far]\n{block}\n[/bridge conversation so far]\n\n{user_text}"


def handle_chat(handler, bot) -> None:
    if not BRIDGE_API_KEY:
        handler._send_json(503, {"ok": False, "error": "bridge_disabled"})
        return
    if not _bearer_ok(handler):
        handler._send_json(403, {"ok": False, "error": "unauthorized"})
        return
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0
    if length <= 0 or length > _MAX_BODY:
        handler._send_json(400, {"ok": False, "error": "bad_length"})
        return
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except Exception:
        handler._send_json(400, {"ok": False, "error": "bad_json"})
        return
    if not isinstance(payload, dict):
        handler._send_json(400, {"ok": False, "error": "bad_payload"})
        return

    text = _compose_text(payload.get("messages") or [])
    if not text:
        handler._send_json(400, {"ok": False, "error": "empty_message"})
        return

    user = payload.get("user") or {}
    try:
        chat_id = int(user.get("id") or 0)
    except (TypeError, ValueError):
        chat_id = 0
    if not chat_id:
        allowed = getattr(bot, "ALLOWED_CHAT_ID", None)
        try:
            chat_id = int(allowed) if allowed else 0
        except (TypeError, ValueError):
            chat_id = 0
    if not chat_id:
        handler._send_json(400, {"ok": False, "error": "missing_user_id"})
        return

    try:
        answer, _usage, latency_ms, _sources = bot._unified_ask(chat_id, text)
        handler._send_json(200, {"ok": True, "reply": str(answer), "latency_ms": latency_ms})
    except Exception as exc:  # noqa: BLE001 - external provider boundary
        print(f"bridge /chat error: {str(exc)[:300]}", flush=True)
        handler._send_json(500, {"ok": False, "error": str(exc)[:200]})

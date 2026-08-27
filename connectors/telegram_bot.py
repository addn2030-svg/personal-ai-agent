# -*- coding: utf-8 -*-
"""Guarded Telegram entrypoint plus unified model routing.

Production imports this module normally, but polling is disabled unless explicitly
opted in with AI_OS_ALLOW_POLLING=1. Model inference may use one OpenRouter API key
for multiple model families while preserving the existing Bedrock path as fallback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import telegram_bot_legacy as _impl
from connectors import model_gateway as _models

_legacy_run = _impl.run
_legacy_ask_bedrock = _impl.ask_bedrock
_legacy_save_conversation = _impl._save_conversation


def _guarded_run():
    if os.environ.get("AI_OS_ALLOW_POLLING", "").strip() != "1":
        raise RuntimeError(
            "Telegram polling is disabled. Production uses webhook mode. "
            "Set AI_OS_ALLOW_POLLING=1 only for an explicit local polling session."
        )
    return _legacy_run()


def _unified_ask(chat_id: int, text: str, sheet_context: str = ""):
    return _models.ask(
        chat_id,
        text,
        system_prompt=_impl.SYSTEM_PROMPT,
        sheet_context=sheet_context,
        sensitive=_impl._clinical_hint(text),
        bedrock_fallback=_legacy_ask_bedrock,
    )


def _save_conversation(cid, iid, question, answer, usage, latency_ms, status, error=""):
    route = _models.last_route()
    if route.get("provider") != "openrouter":
        return _legacy_save_conversation(
            cid, iid, question, answer, usage, latency_ms, status, error
        )

    clinical = _impl._category(question) == "CLINICAL_PRIVATE"
    review = "PENDING" if clinical else "NOT_REQUIRED"
    row = [
        cid, iid, _impl._now(), "OPENROUTER", route.get("model", _models.AI_MANAGER_MODEL),
        _impl._redact(question), _impl._redact(answer),
        usage.get("inputTokens", ""), usage.get("outputTokens", ""),
        latency_ms, status, review, str(error)[:500],
    ]
    try:
        _impl._append(_impl.CONVERSATION_TAB, row)
        return True
    except Exception as exc:  # noqa: BLE001 - connector boundary
        print(f"Google conversation save error: {exc}", flush=True)
        return False


def _command_ai_status(chat_id: int):
    status = _models.status()
    models = status["models"]
    lines = [
        "🤖 Model Gateway",
        f"General: {status['desired_general_provider']}",
        f"Clinical: {status['desired_clinical_provider']}",
        f"OpenRouter: {'configured ✅' if status['openrouter_configured'] else 'not configured'}",
        f"Manager: {models['manager']}",
        f"Critic: {models['critic']}",
        f"Google adviser: {models['google']}",
    ]
    if status["clinical_policy"].get("zdr"):
        lines.append("Clinical OpenRouter policy (if enabled): ZDR + data_collection=deny")
    _impl.send(chat_id, "\n".join(lines))


_impl.run = _guarded_run
_impl.ask_bedrock = _unified_ask  # compatibility name retained for existing callers
_impl._save_conversation = _save_conversation
_impl.command_ai_status = _command_ai_status

if __name__ == "__main__":
    _guarded_run()
else:
    # Importers receive the implementation module itself so runtime patches modify
    # the same globals used by command handlers.
    sys.modules[__name__] = _impl

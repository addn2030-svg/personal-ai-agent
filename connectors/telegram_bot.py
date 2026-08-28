# -*- coding: utf-8 -*-
"""Guarded Telegram entrypoint, unified model routing, delegation, and missions."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import telegram_bot_legacy as _impl
from connectors import model_gateway as _models
from connectors import task_delegation as _team
from connectors import bedrock_team as _bedrock_team

_legacy_run = _impl.run
_legacy_ask_bedrock = _impl.ask_bedrock
_legacy_save_conversation = _impl._save_conversation
_legacy_handle_message = _impl.handle_message
_legacy_configure_commands = _impl.configure_commands
_legacy_command_start = _impl.command_start


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
        return _legacy_save_conversation(cid, iid, question, answer, usage, latency_ms, status, error)

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
    except Exception as exc:
        print(f"Google conversation save error: {exc}", flush=True)
        return False


def _command_ai_status(chat_id: int):
    status = _models.status()
    role_models = status["models"]
    lines = [
        "🤖 Model Gateway",
        f"General: {status['desired_general_provider']}",
        f"Clinical: {status['desired_clinical_provider']}",
        f"OpenRouter: {'configured ✅' if status['openrouter_configured'] else 'not configured'}",
        f"Manager: {role_models['manager']}",
        f"Critic: {role_models['critic']}",
        f"Google adviser: {role_models['google']}",
    ]
    if status["clinical_policy"].get("zdr"):
        lines.append("Clinical OpenRouter policy (if enabled): ZDR + data_collection=deny")
    _impl.send(chat_id, "\n".join(lines))


def _command_start(chat_id: int):
    _legacy_command_start(chat_id)
    _impl.send(
        chat_id,
        "\n🧠 فريق الوكلاء v0.9\n"
        "/agents — حالة فريق النماذج ومساراته\n"
        "/bedrock_test — اختبار صغير لـ Claude وGPT Luna على Bedrock\n"
        "/delegate auto المهمة — المدير يختار الوكيل\n"
        "/delegate claude|gpt|gemini المهمة — تكليف مباشر\n"
        "/council السؤال — مراجعة من الفريق\n"
        "/mission [lean|standard|deep] الهدف — مهمة بميزانية tokens\n"
        "لا توجد أدوات خارجية تلقائية داخل /mission؛ أي تنفيذ حساس يبقى خلف الموافقة.",
    )


def _format_delegate(result: _team.AgentResult) -> str:
    label = _team.ROLE_LABELS.get(result.executed_by, result.executed_by)
    fallback = "\n⚠️ المسار الأساسي تعذر؛ تم استخدام fallback." if result.fallback else ""
    return (
        f"✅ Delegated to: {label}\n"
        f"Provider: {result.provider}\n"
        f"Model: {result.model}{fallback}\n\n"
        f"{result.answer}"
    )


def _format_probe_item(label: str, item: dict) -> str:
    model = item.get("model", "unknown")
    if item.get("ok"):
        usage = item.get("usage") or {}
        token_text = ""
        if usage:
            token_text = f" | in={usage.get('inputTokens', '?')} out={usage.get('outputTokens', '?')}"
        return f"✅ {label}: {model} | {item.get('latency_ms', '?')} ms{token_text}"
    error = str(item.get("error", "unknown error"))[:500]
    return f"❌ {label}: {model}\n{error}"


def _command_bedrock_test(chat_id: int):
    result = _bedrock_team.probe()
    lines = [
        "🧪 Bedrock Team Test v0.9.1",
        _format_probe_item("Manager / Claude", result.get("manager") or {}),
        _format_probe_item("Lean specialist / GPT Luna", result.get("lean") or {}),
        "This test uses tiny prompts only; no conversation history or Sheets context is sent.",
    ]
    _impl.send(chat_id, "\n\n".join(lines))


def _send_chunks(chat_id: int, text: str, chunk_size: int = 3500):
    value = str(text or "")
    if not value:
        return
    for start in range(0, len(value), chunk_size):
        _impl.send(chat_id, value[start:start + chunk_size])


def _delegated_handle_message(message: dict):
    raw = (message.get("text") or message.get("caption") or "").strip()
    command = raw.split()[0].split("@")[0].lower() if raw else ""
    if command not in {"/agents", "/bedrock_test", "/delegate", "/council", "/mission"}:
        return _legacy_handle_message(message)

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    if not _impl._authorized(chat_id, chat.get("type", "")):
        _impl.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
        return

    text, kind, attachment = _impl._message_payload(message)
    iid = _impl._local_capture(text, message, kind)
    if kind != "TEXT":
        _impl.send(chat_id, "استخدم أوامر الفريق كنص. دعم التكليف الصوتي سيأتي لاحقًا.")
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error="TEAM_COMMAND_TEXT_ONLY")
        return

    try:
        _impl.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        if command == "/agents":
            answer = _team.agents_status_text()
            _impl.send(chat_id, answer)
        elif command == "/bedrock_test":
            _command_bedrock_test(chat_id)
        elif command == "/delegate":
            value = text[len(command):].strip()
            result = _team.delegate(chat_id, value, bedrock_fallback=_legacy_ask_bedrock)
            _impl.send(chat_id, _format_delegate(result))
        elif command == "/council":
            question = text[len(command):].strip()
            answer = _team.council(chat_id, question, bedrock_fallback=_legacy_ask_bedrock)
            _send_chunks(chat_id, answer)
        else:
            objective = text[len(command):].strip()
            answer = _team.mission(chat_id, objective, bedrock_fallback=_legacy_ask_bedrock)
            _send_chunks(chat_id, answer)
        _impl._save_intake(iid, message, text, kind, attachment, "COMPLETED")
    except ValueError as exc:
        _impl.send(chat_id, "❌ " + str(exc))
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)
    except Exception as exc:
        safe = _models._safe_error(exc)
        _impl.send(chat_id, "❌ تعذر تنفيذ مهمة الوكيل: " + safe)
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=safe)


def _configure_commands():
    _legacy_configure_commands()
    try:
        commands = _impl.api("getMyCommands") or []
        existing = {str(item.get("command", "")) for item in commands}
        additions = [
            {"command": "agents", "description": "حالة فريق النماذج ومساراته"},
            {"command": "bedrock_test", "description": "اختبار Claude وGPT Luna على Bedrock"},
            {"command": "delegate", "description": "تكليف وكيل أو اختيار تلقائي"},
            {"command": "council", "description": "مراجعة سؤال بواسطة فريق الذكاء"},
            {"command": "mission", "description": "مهمة مشتركة بميزانية tokens"},
        ]
        commands.extend(item for item in additions if item["command"] not in existing)
        _impl.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
    except Exception as exc:
        print(f"Telegram command menu extension warning: {exc}", flush=True)


_impl.run = _guarded_run
_impl.ask_bedrock = _unified_ask
_impl._save_conversation = _save_conversation
_impl.command_ai_status = _command_ai_status
_impl.command_start = _command_start
_impl.handle_message = _delegated_handle_message
_impl.configure_commands = _configure_commands

if __name__ == "__main__":
    _guarded_run()
else:
    sys.modules[__name__] = _impl

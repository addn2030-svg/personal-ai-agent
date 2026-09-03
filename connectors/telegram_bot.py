# -*- coding: utf-8 -*-
"""Guarded Telegram entrypoint, unified model routing, delegation, missions, and Super Manager."""
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
from connectors import ops_context as _ops_context
from connectors import super_manager as _super_manager
from connectors import strategic_creator as _strategic_creator
from connectors import strategic_shadow_generator as _strategic_shadow

_legacy_run = _impl.run
_legacy_ask_bedrock = _impl.ask_bedrock
_legacy_save_conversation = _impl._save_conversation
_legacy_handle_message = _impl.handle_message
_legacy_configure_commands = _impl.configure_commands
_legacy_command_start = _impl.command_start

_MANAGER_COMMANDS = {"/manager", "/manager_shadow", "/manager_status", "/possibility_shadow", "/possibility_compare"}
_NO_PERSIST_COMMANDS = {"/possibility_shadow", "/possibility_compare"}
_TEAM_COMMANDS = {"/agents", "/bedrock_test", "/context_test", "/delegate", "/council", "/mission"} | _MANAGER_COMMANDS


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


def _command_possibility_shadow(chat_id: int, objective: str):
    """Generate a read-only strategic preview. This command has no write path."""
    goal = (objective or "").strip()
    if not _strategic_creator.enabled():
        _impl.send(
            chat_id,
            "🧪 Possibility Shadow غير مفعّل. لم يتم استدعاء أي نموذج أو كتابة أي بيانات.",
        )
        return
    if not goal:
        raise ValueError("اكتب القرار بعد /possibility_shadow")

    context = _super_manager.build_context(goal)

    def generate(prompt: str) -> str:
        answer, _provider, _model, _usage = _super_manager.lean._bedrock_manager(
            prompt,
            max_tokens=700,
            chat_id=chat_id,
            bedrock_fallback=_legacy_ask_bedrock,
        )
        return answer

    preview = _strategic_shadow.generate_preview(goal, context.text, generate)
    _send_chunks(chat_id, _strategic_shadow.preview_text(preview))


def _command_possibility_compare(chat_id: int, objective: str):
    """Compare baseline reasoning with a strategic preview; persist neither."""
    goal = (objective or "").strip()
    if not _strategic_creator.enabled():
        _impl.send(
            chat_id,
            "🧪 Possibility Compare غير مفعّل. لم يتم استدعاء أي نموذج أو حفظ بيانات.",
        )
        return
    if not goal:
        raise ValueError("اكتب القرار بعد /possibility_compare")

    context = _super_manager.build_context(goal)
    baseline_prompt = _super_manager.build_prompt(
        goal, context, include_strategic=False
    )

    baseline, baseline_provider, baseline_model, _usage = (
        _super_manager.lean._bedrock_manager(
            baseline_prompt,
            max_tokens=700,
            chat_id=chat_id,
            bedrock_fallback=_legacy_ask_bedrock,
        )
    )

    def generate(prompt: str) -> str:
        answer, _provider, _model, _candidate_usage = (
            _super_manager.lean._bedrock_manager(
                prompt,
                max_tokens=700,
                chat_id=chat_id,
                bedrock_fallback=_legacy_ask_bedrock,
            )
        )
        return answer

    preview = _strategic_shadow.generate_preview(goal, context.text, generate)
    source_text = "+".join(context.sources) if context.sources else "none"
    output_chunks = (
        "🧪 POSSIBILITY COMPARE — READ ONLY / NOT SAVED\n"
        f"Context: {source_text}\n\n"
        "===== CURRENT MANAGER =====\n"
        f"Route: {baseline_provider}:{baseline_model}\n"
        f"{baseline}\n\n"
        "===== STRATEGIC PREVIEW =====\n"
        f"{_strategic_shadow.preview_text(preview)}"
    )
    _send_chunks(chat_id, output_chunks)


def _command_start(chat_id: int):
    _legacy_command_start(chat_id)
    _impl.send(
        chat_id,
        "\n🧠 فريق الوكلاء + Super Manager\n"
        "/manager الطلب — رئيس الأركان: يربط، يكشف النقص، يوصي\n"
        "/manager_shadow الطلب — مقارنة Legacy مع Super Manager بلا أثر خارجي\n"
        "/manager_status — حالة طبقة المدير\n"
        "/possibility_shadow القرار — معاينة احتمال تجريبي دون كتابة\n"
        "/possibility_compare القرار — مقارنة المدير والمعاينة دون حفظ\n"
        "/agents — حالة فريق النماذج ومساراته\n"
        "/bedrock_test — اختبار صغير لـ Claude والـLean specialist على Bedrock\n"
        "/context_test tomorrow — اختبار Calendar/Sheets بدون AI tokens\n"
        "/delegate auto المهمة — المدير يختار الوكيل\n"
        "/delegate claude|gpt|gemini المهمة — تكليف مباشر\n"
        "/council السؤال — مراجعة من الفريق\n"
        "/mission [lean|standard|deep] الهدف — مهمة بميزانية tokens\n"
        "أي أثر خارجي يبقى خلف الاقتراح/المعاينة/الموافقة/التنفيذ.",
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
        "🧪 Bedrock Team Test v0.9.2",
        _format_probe_item("Manager / Claude", result.get("manager") or {}),
        _format_probe_item("Lean specialist", result.get("lean") or {}),
        "This test uses tiny prompts only; no conversation history or Sheets context is sent.",
    ]
    _impl.send(chat_id, "\n\n".join(lines))


def _command_context_test(chat_id: int, goal: str):
    value = (goal or "").strip() or "priorities tomorrow"
    result = _ops_context.probe(value)
    sources = "+".join(result.get("sources") or []) or "none"
    lines = [
        "🧪 Ops Context Test v0.9.3a — no model call",
        f"Goal: {value}",
        f"Triggered: {'YES ✅' if result.get('triggered') else 'NO'}",
        f"Sources: {sources}",
        f"Calendar rows: {result.get('calendar_rows', 0)}",
        f"Sheet rows: {result.get('sheet_rows', 0)}",
        f"Chars: {result.get('chars', 0)}",
    ]
    errors = result.get("errors") or []
    if errors:
        lines.append("Safe errors:\n- " + "\n- ".join(str(x) for x in errors[:3]))
    preview = str(result.get("preview") or "").strip()
    if preview:
        lines.append("Preview (already privacy-filtered):\n" + preview[:1200])
    else:
        lines.append("Preview: empty")
    lines.append("AI/model calls: 0")
    _send_chunks(chat_id, "\n\n".join(lines))


def _send_chunks(chat_id: int, text: str, chunk_size: int = 3500):
    value = str(text or "")
    if not value:
        return
    for start in range(0, len(value), chunk_size):
        _impl.send(chat_id, value[start:start + chunk_size])


def _natural_manager_request(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    if not text or text.startswith("/"):
        return False, ""
    lower = text.lower()
    for prefix in ("مدير ", "manager "):
        if lower.startswith(prefix):
            return True, text[len(prefix):].strip()
    if os.environ.get("AI_SUPER_MANAGER_DEFAULT", "0").strip() == "1":
        return True, text
    return False, ""


def _delegated_handle_message(message: dict):
    raw = (message.get("text") or message.get("caption") or "").strip()
    command = raw.split()[0].split("@")[0].lower() if raw else ""
    natural_manager, natural_objective = _natural_manager_request(raw)
    if command not in _TEAM_COMMANDS and not natural_manager:
        return _legacy_handle_message(message)

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    if not _impl._authorized(chat_id, chat.get("type", "")):
        _impl.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
        return

    text, kind, attachment = _impl._message_payload(message)
    no_persist = command in _NO_PERSIST_COMMANDS
    iid = (
        f"SHADOW-{chat_id}-{message.get('message_id', '')}"
        if no_persist
        else _impl._local_capture(text, message, kind)
    )
    if kind != "TEXT":
        _impl.send(chat_id, "استخدم أوامر الفريق/المدير كنص. الصوت يبقى في مسار التفريغ الحالي.")
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error="TEAM_COMMAND_TEXT_ONLY")
        return

    try:
        _impl.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        if natural_manager:
            answer = _super_manager.manager(chat_id, natural_objective, bedrock_fallback=_legacy_ask_bedrock)
            _send_chunks(chat_id, answer)
        elif command == "/manager":
            objective = text[len(command):].strip()
            answer = _super_manager.manager(chat_id, objective, bedrock_fallback=_legacy_ask_bedrock)
            _send_chunks(chat_id, answer)
        elif command == "/manager_shadow":
            objective = text[len(command):].strip()
            answer = _super_manager.shadow(chat_id, objective, bedrock_fallback=_legacy_ask_bedrock)
            _send_chunks(chat_id, answer)
        elif command == "/manager_status":
            _impl.send(chat_id, _super_manager.status_text())
        elif command == "/possibility_shadow":
            _command_possibility_shadow(chat_id, text[len(command):].strip())
        elif command == "/possibility_compare":
            _command_possibility_compare(chat_id, text[len(command):].strip())
        elif command == "/agents":
            answer = _team.agents_status_text()
            _impl.send(chat_id, answer)
        elif command == "/bedrock_test":
            _command_bedrock_test(chat_id)
        elif command == "/context_test":
            _command_context_test(chat_id, text[len(command):].strip())
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
        if not no_persist:
            _impl._save_intake(iid, message, text, kind, attachment, "COMPLETED")
    except ValueError as exc:
        _impl.send(chat_id, "❌ " + str(exc))
        if not no_persist:
            _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)
    except Exception as exc:
        safe = _models._safe_error(exc)
        _impl.send(chat_id, "❌ تعذر تنفيذ مهمة الوكيل: " + safe)
        if not no_persist:
            _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=safe)


def _configure_commands():
    _legacy_configure_commands()
    try:
        commands = _impl.api("getMyCommands") or []
        existing = {str(item.get("command", "")) for item in commands}
        additions = [
            {"command": "manager", "description": "رئيس الأركان: تحليل وربط وتوصية"},
            {"command": "manager_shadow", "description": "قارن Legacy وSuper Manager بلا تنفيذ"},
            {"command": "manager_status", "description": "حالة Super Manager"},
            {"command": "possibility_shadow", "description": "معاينة احتمال دون كتابة"},
            {"command": "possibility_compare", "description": "مقارنة المدير والمعاينة دون حفظ"},
            {"command": "agents", "description": "حالة فريق النماذج ومساراته"},
            {"command": "bedrock_test", "description": "اختبار Claude والـLean specialist على Bedrock"},
            {"command": "context_test", "description": "اختبار سياق Calendar/Sheets بدون AI"},
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

# -*- coding: utf-8 -*-
"""Guarded Telegram entrypoint, model routing, delegation, and Google knowledge."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import google_knowledge as _knowledge
from connectors import model_gateway as _models
from connectors import task_delegation as _team
from connectors import telegram_bot_legacy as _impl

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
    status = _models.status(); models = status["models"]
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


def _command_start(chat_id: int):
    _legacy_command_start(chat_id)
    _impl.send(
        chat_id,
        "\n🧠 فريق الوكلاء v0.7\n"
        "/agents — حالة Claude + GPT + Gemini\n"
        "/delegate auto المهمة — المدير يختار الوكيل\n"
        "/council السؤال — مراجعة من الفريق\n"
        "/google_access — فحص وصول البوت الحقيقي إلى Google\n"
        "/knowledge كلمة — بحث في مصادر المعرفة المسموحة\n"
        "/read رابط — قراءة Doc/Sheet/Text مسموح\n"
        "/sheetcheck رابط — عرض اسم الشيت والتبويبات\n"
        "الكتابة إلى ملفات المعرفة لا تتم دون اعتمادك.",
    )


def _format_delegate(result: _team.AgentResult) -> str:
    label = _team.ROLE_LABELS.get(result.executed_by, result.executed_by)
    fallback = "\n⚠️ OpenRouter تعذر؛ تم التنفيذ عبر Bedrock." if result.fallback else ""
    return f"✅ Delegated to: {label}\nProvider: {result.provider}\nModel: {result.model}{fallback}\n\n{result.answer}"


def _send_chunks(chat_id: int, text: str, chunk_size: int = 3600):
    text = str(text or "")
    if not text:
        _impl.send(chat_id, "لا توجد بيانات نصية للعرض.")
        return
    for start in range(0, len(text), chunk_size):
        _impl.send(chat_id, text[start:start + chunk_size])


def _access_text() -> str:
    report = _knowledge.access_report()
    lines = ["🔐 Google Knowledge Access v0.7", f"Service account: {report['service_account'] or 'unknown'}", "", "📊 Spreadsheets:"]
    for row in report["spreadsheets"]:
        lines.append(f"{'✅' if row['ok'] else '❌'} {row.get('title') or row['id']}")
    lines.append("\n📁 Knowledge folders:")
    for row in report["folders"]:
        lines.append(f"{'✅' if row['ok'] else '❌'} {row.get('title') or row['id']}")
    lines.append("\n❌ يعني أن هذا المجلد/الشيت يحتاج مشاركة مع Service Account أعلاه أو تصحيح الرابط.")
    return "\n".join(lines)


def _knowledge_text(query: str) -> str:
    rows = _knowledge.search(query, max_results=20)
    if not rows:
        return "🔎 لم أجد نتائج مؤكدة في مصادر المعرفة المسموحة."
    lines = [f"🔎 نتائج المعرفة: {query}"]
    for i, row in enumerate(rows, 1):
        name = row.get("name") or "بدون اسم"
        url = row.get("url") or ""
        source = row.get("tab") or row.get("source") or "Drive"
        lines.append(f"{i}. {name}\n   المصدر: {source}\n   {url}".rstrip())
    return "\n".join(lines)


def _knowledge_handle_message(message: dict):
    raw = (message.get("text") or message.get("caption") or "").strip()
    command = raw.split()[0].split("@")[0].lower() if raw else ""
    handled = {"/agents", "/delegate", "/council", "/google_access", "/knowledge", "/read", "/sheetcheck"}
    if command not in handled:
        return _legacy_handle_message(message)

    chat = message.get("chat") or {}; chat_id = chat.get("id")
    if chat_id is None:
        return
    if not _impl._authorized(chat_id, chat.get("type", "")):
        _impl.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل."); return

    text, kind, attachment = _impl._message_payload(message)
    iid = _impl._local_capture(text, message, kind)
    if kind != "TEXT":
        _impl.send(chat_id, "استخدم هذه الأوامر كنص.")
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error="COMMAND_TEXT_ONLY"); return

    try:
        _impl.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        if command == "/agents":
            answer = _team.agents_status_text(); _impl.send(chat_id, answer)
        elif command == "/delegate":
            value = text[len(command):].strip()
            _impl.send(chat_id, _format_delegate(_team.delegate(chat_id, value, bedrock_fallback=_legacy_ask_bedrock)))
        elif command == "/council":
            _impl.send(chat_id, _team.council(chat_id, text[len(command):].strip(), bedrock_fallback=_legacy_ask_bedrock))
        elif command == "/google_access":
            _impl.send(chat_id, _access_text())
        elif command == "/knowledge":
            _impl.send(chat_id, _knowledge_text(text[len(command):].strip()))
        elif command == "/read":
            result = _knowledge.read(text[len(command):].strip())
            header = f"📄 {result['name']}\nType: {result['mimeType']}\n{result.get('url','')}\n\n"
            body = result.get("text") or result.get("note") or "لا يوجد نص قابل للقراءة."
            _send_chunks(chat_id, header + body)
        else:
            info = _knowledge.sheet_summary(text[len(command):].strip())
            _impl.send(chat_id, "📊 " + info["title"] + "\n" + "\n".join(f"• {x}" for x in info["tabs"]))
        _impl._save_intake(iid, message, text, kind, attachment, "COMPLETED")
    except (ValueError, PermissionError) as exc:
        _impl.send(chat_id, "❌ " + str(exc))
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)
    except Exception as exc:
        safe = _models._safe_error(exc)
        _impl.send(chat_id, "❌ Google Knowledge: " + safe)
        _impl._save_intake(iid, message, text, kind, attachment, "ERROR", error=safe)


def _configure_commands():
    _legacy_configure_commands()
    try:
        commands = _impl.api("getMyCommands") or []
        existing = {str(item.get("command", "")) for item in commands}
        additions = [
            {"command": "agents", "description": "حالة فريق Claude وGPT وGemini"},
            {"command": "delegate", "description": "تكليف وكيل أو اختيار تلقائي"},
            {"command": "council", "description": "مراجعة سؤال بواسطة فريق الذكاء"},
            {"command": "google_access", "description": "فحص صلاحيات Google للبوت"},
            {"command": "knowledge", "description": "بحث في مصادر المعرفة"},
            {"command": "read", "description": "قراءة ملف معرفة مسموح"},
            {"command": "sheetcheck", "description": "فحص شيت مسموح"},
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
_impl.handle_message = _knowledge_handle_message
_impl.configure_commands = _configure_commands

if __name__ == "__main__":
    _guarded_run()
else:
    sys.modules[__name__] = _impl

# -*- coding: utf-8 -*-
"""Owner-only Telegram commands for Active Multi-AI Manager.

Installed after brief_runtime so this wrapper is the outermost command boundary.
Unauthorized custom commands are dropped instead of delegated, preventing older
runtime wrappers from accidentally bypassing owner authorization.
"""
from __future__ import annotations

import re

CUSTOM_RE = re.compile(r"^/(agents|council|modeltest)(?:@\w+)?(?:\s+(.*))?$", re.I | re.S)


def _authorized(bot, message: dict) -> bool:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return False
    try:
        return bool(bot._authorized(chat_id, chat.get("type", "")))
    except Exception:
        return False


def _agents(bot, chat_id: int):
    from store import Store

    state = Store().rows_all()
    sources = state.get("ai_sources", [])
    external_items = [
        x for x in state.get("unified_inbox", [])
        if (x.get("metadata") or {}).get("origin") == "external_ai"
    ]
    open_conflicts = len([c for c in state.get("contradictions", []) if c.get("status") == "OPEN"])
    pending = len([
        d for d in state.get("decision_requests", [])
        if d.get("status") == "PENDING" and str(d.get("id", "")).startswith("DR-AI-")
    ])
    councils = len([x for x in state.get("trust_snapshots", []) if x.get("kind") == "AI_COUNCIL"])

    lines = ["🤖 AI TEAM — Active Multi-AI Manager"]
    if not sources:
        lines.append("لا توجد مصادر AI مسجلة حتى الآن.")
    for src in sorted(sources, key=lambda x: str(x.get("source"))):
        enabled = "🟢" if src.get("enabled", True) else "⚪"
        lines.append(
            f"{enabled} {src.get('source')} — {src.get('role', 'adviser')} | "
            f"trust L{src.get('trust_level', 1)} | events {src.get('events_received', 0)} | "
            f"last {src.get('last_seen', '—')}"
        )
    lines.extend([
        f"\n📥 External AI updates: {len(external_items)}",
        f"🧠 AI Councils saved: {councils}",
        f"⚠️ Open contradictions: {open_conflicts}",
        f"🧭 AI decisions pending: {pending}",
    ])
    bot.send(chat_id, "\n".join(lines)[:3900])


def _council(bot, chat_id: int, question: str):
    if not question:
        bot.send(chat_id, "الاستخدام: /council ثم اكتب القرار أو السؤال الذي تريد عرضه على GPT + Claude + Gemini.")
        return
    if bot._clinical_hint(question):
        bot.send(chat_id, "🔐 لا يتم إرسال المحتوى السريري/الحساس إلى AI Council متعدد المزودين.")
        return

    from engine import ai_council

    bot.send(chat_id, "🧠 أشغّل AI Council: Claude + GPT + Gemini ثم Judge...")
    record = ai_council.consult(question, persist=True)
    bot.send(chat_id, ai_council.format_for_telegram(record))


def _modeltest(bot, chat_id: int):
    from connectors import model_gateway

    bot.send(chat_id, "🧪 أختبر OpenRouter وBedrock باختبار حي صغير...")
    result = model_gateway.live_probe()
    orow = result["openrouter"]
    brow = result["bedrock"]
    lines = ["🧪 Model Readiness"]
    lines.append(
        f"{'✅' if orow.get('ok') else '❌'} OpenRouter — "
        + str(orow.get("model") or orow.get("detail") or "not configured")[:180]
    )
    if orow.get("latency_ms") is not None:
        lines[-1] += f" | {orow['latency_ms']} ms"
    lines.append(
        f"{'✅' if brow.get('ok') else '❌'} Bedrock — "
        + str(brow.get("model") or brow.get("detail") or "not configured")[:180]
    )
    if brow.get("latency_ms") is not None:
        lines[-1] += f" | {brow['latency_ms']} ms"
    policy = result["policy"]
    lines.append(
        f"Routing: general={policy['general_primary']} | clinical={policy['clinical_primary']} | "
        f"OR→Bedrock fallback={'on' if policy['openrouter_to_bedrock_fallback'] else 'off'}"
    )
    bot.send(chat_id, "\n".join(lines)[:3900])


def install(bot):
    if getattr(bot, "_AI_OS_RUNTIME_COMMANDS", False):
        return
    original = bot.handle_message

    def handle_message(message: dict):
        text = (message.get("text") or "").strip()
        match = CUSTOM_RE.match(text)
        if not match:
            return original(message)

        # Never delegate a recognized custom command when the owner check fails.
        # Older wrappers may not have their own authorization boundary.
        if not _authorized(bot, message):
            return None

        chat_id = (message.get("chat") or {}).get("id")
        command = match.group(1).lower()
        arg = (match.group(2) or "").strip()
        try:
            if command == "agents":
                _agents(bot, chat_id)
            elif command == "council":
                _council(bot, chat_id, arg)
            elif command == "modeltest":
                _modeltest(bot, chat_id)
        except Exception as exc:  # noqa: BLE001 - command boundary
            bot.send(chat_id, f"❌ تعذر تنفيذ /{command}: {str(exc)[:220]}")
        return None

    bot.handle_message = handle_message
    bot._AI_OS_RUNTIME_COMMANDS = True

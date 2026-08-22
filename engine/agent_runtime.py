# -*- coding: utf-8 -*-
"""Runtime orchestration: bounded memory + state + lightweight knowledge retrieval."""
from __future__ import annotations
import datetime as dt
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
from store import Store, log_event

ALLOWED_EXT = {".md", ".txt", ".yaml", ".yml"}
MAX_MEMORY_TURNS = int(os.environ.get("AGENT_MEMORY_TURNS", "10"))
MAX_CONTEXT_CHARS = int(os.environ.get("AGENT_CONTEXT_CHARS", "14000"))


def _tokens(text):
    return set(re.findall(r"[\w\u0600-\u06FF]{3,}", (text or "").lower()))


def _safe(text):
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[PRIVATE_EMAIL]", text or "", flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)", "[PRIVATE_PHONE]", text)
    return text


def route_domain(query):
    q = query.lower()
    if re.search(r"patient|مريض|pain|ألم|علاج|clinical|تشخيص|movement|حركة", q):
        return "clinical"
    if re.search(r"project|مشروع|task|مهمة|قرار|decision|meeting|اجتماع", q):
        return "management"
    if re.search(r"marketing|تسويق|client|عميل|business|عمل", q):
        return "business"
    if re.search(r"learn|تعلم|دورة|course|training|تدريب", q):
        return "learning"
    return "general"


def recent_messages(chat_id, limit=None):
    limit = limit or MAX_MEMORY_TURNS * 2
    rows = Store().rows_all().get("conversation_memory", [])
    rows = [r for r in rows if str(r.get("chat_id")) == str(chat_id)]
    return rows[-limit:]


def remember(chat_id, role, content, message_id="", category="GENERAL"):
    store = Store()
    state = store.rows_all()
    rows = state.setdefault("conversation_memory", [])
    rows.append({
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "chat_id": str(chat_id), "role": role, "content": _safe(content)[:8000],
        "message_id": str(message_id), "category": category,
    })
    per_chat = [r for r in rows if str(r.get("chat_id")) == str(chat_id)]
    if len(per_chat) > 60:
        remove = {id(x) for x in per_chat[:-60]}
        rows[:] = [x for x in rows if id(x) not in remove]
    store.commit(state, "conversation_remember", chat_id=str(chat_id), role=role)
    log_event("CONVERSATION_MEMORY_ADDED", chat_id=str(chat_id), role=role)


def _state_context():
    state = Store().rows_all()
    chunks = []
    for key in ("projects", "tasks", "decisions", "waiting_for", "decision_requests"):
        rows = state.get(key, [])
        if rows:
            chunks.append(f"{key}: {str(rows[-12:])[:3000]}")
    return "\n".join(chunks)


def _knowledge_context(query):
    wanted = _tokens(query)
    scored = []
    for folder in (BASE / "knowledge", BASE / "prompts", BASE / "materials"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_EXT:
                continue
            try:
                text = path.read_text(encoding="utf-8")[:24000]
            except OSError:
                continue
            score = len(wanted & _tokens(path.name + " " + text[:6000]))
            if score:
                scored.append((score, str(path.relative_to(BASE)), _safe(text)))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    used = 0
    sources = []
    for _, name, text in scored[:5]:
        chunk = text[:3500]
        if used + len(chunk) > 9000:
            break
        out.append(f"--- SOURCE {name} ---\n{chunk}")
        sources.append(name)
        used += len(chunk)
    return "\n".join(out), sources


def build_context(chat_id, query):
    knowledge, sources = _knowledge_context(query)
    state = _state_context()
    context = (
        f"ROUTED DOMAIN: {route_domain(query)}\n"
        "Use the following private, provenance-aware context only when relevant. "
        "If evidence is absent or conflicting, say so.\n"
        f"\nOPERATIONAL STATE\n{state}\n\nRETRIEVED KNOWLEDGE\n{knowledge}"
    )
    return context[:MAX_CONTEXT_CHARS], sources


def bedrock_messages(chat_id, query):
    history = recent_messages(chat_id)
    messages = []
    for row in history[-MAX_MEMORY_TURNS * 2:]:
        role = row.get("role")
        if role in {"user", "assistant"}:
            messages.append({"role": role, "content": [{"text": str(row.get("content", ""))[:5000]}]})
    messages.append({"role": "user", "content": [{"text": query}]})
    return messages

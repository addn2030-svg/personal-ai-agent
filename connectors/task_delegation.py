# -*- coding: utf-8 -*-
"""Lightweight multi-agent task delegation for the production Telegram manager.

This module delegates *reasoning* to configured model roles. It does not grant any
model browser, Drive, Calendar, Sheets, or outbound-message permissions. Tools and
external data connectors are added separately and must provide evidence explicitly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from connectors import model_gateway as models

AGENT_ALIASES = {
    "auto": "auto",
    "claude": "claude",
    "manager": "claude",
    "مدير": "claude",
    "gpt": "gpt",
    "critic": "gpt",
    "ناقد": "gpt",
    "gemini": "gemini",
    "research": "gemini",
    "باحث": "gemini",
}

ROLE_MODELS = {
    "claude": lambda: models.AI_MANAGER_MODEL,
    "gpt": lambda: models.AI_CRITIC_MODEL,
    "gemini": lambda: models.AI_GOOGLE_MODEL,
}

ROLE_LABELS = {
    "claude": "Claude — Manager",
    "gpt": "GPT — Critic",
    "gemini": "Gemini — Researcher",
}

_RESEARCH_RE = re.compile(
    r"research|search|find|discover|trend|scan|instagram|social|sources|latest|"
    r"ابحث|بحث|اكتشف|استكشف|ترند|انستغرام|إنستغرام|منصة|مصادر|الأحدث|احدث",
    re.I,
)
_CRITIC_RE = re.compile(
    r"review|critic|verify|validate|risk|audit|compare|contract|weakness|"
    r"راجع|دقق|تحقق|مخاطر|تدقيق|قارن|عقد|ثغرات|نقد",
    re.I,
)
_PRIVATE_RE = re.compile(
    r"\bmrn\b|medical\s*record|رقم\s*الملف|رقم\s*الهوية|هوية\s*المريض|"
    r"patient\s*(name|id)|اسم\s*المريض|\b05\d{8}\b|\+9665\d{8}",
    re.I,
)


@dataclass
class AgentResult:
    requested: str
    executed_by: str
    provider: str
    model: str
    answer: str
    fallback: bool = False


def contains_private_data(text: str) -> bool:
    """Detect private identifiers without treating general medical education as private."""
    return bool(_PRIVATE_RE.search(text or ""))


def choose_agent(task: str) -> str:
    """Deterministic auto-router: research -> Gemini, verification -> GPT, else Claude."""
    if _RESEARCH_RE.search(task or ""):
        return "gemini"
    if _CRITIC_RE.search(task or ""):
        return "gpt"
    return "claude"


def parse_delegate(value: str) -> tuple[str, str]:
    text = (value or "").strip()
    if not text:
        return "auto", ""
    first, *rest = text.split(maxsplit=1)
    alias = AGENT_ALIASES.get(first.lower())
    if alias:
        return alias, (rest[0].strip() if rest else "")
    return "auto", text


def _system_for(agent: str) -> str:
    common = (
        "You are one adviser inside Abdulrahman AI OS. Work only from the task and "
        "evidence supplied to you. Do not claim you browsed the web, Instagram, Google "
        "Drive, or any external service unless evidence from that connector is included. "
        "Separate facts, assumptions, and recommendations. Be concise and practical."
    )
    if agent == "gemini":
        return common + " Focus on research framing, discovery angles, source gaps, and what evidence should be collected."
    if agent == "gpt":
        return common + " Focus on verification, weaknesses, contradictions, risks, and decision quality."
    return common + " Focus on synthesis, priorities, decisions, and next actions."


def _openrouter_agent(agent: str, task: str) -> AgentResult:
    model = ROLE_MODELS[agent]()
    answer, _usage, _latency = models.openrouter_chat(
        model=model,
        messages=[
            {"role": "system", "content": _system_for(agent)},
            {"role": "user", "content": task},
        ],
        sensitive=False,
        max_tokens=900,
        temperature=0.2,
    )
    return AgentResult(agent, agent, "openrouter", models.last_route().get("model") or model, answer)


def _bedrock_manager(chat_id: int, task: str, bedrock_fallback, *, requested: str, fallback: bool) -> AgentResult:
    if bedrock_fallback is None:
        raise RuntimeError("Bedrock manager fallback is unavailable")
    prompt = (
        "Delegated manager task. Execute as the protected Claude/Bedrock manager. "
        "Do not claim external browsing or tool access unless evidence is included.\n\n" + task
    )
    answer, _usage, _latency, _sources = bedrock_fallback(chat_id, prompt, sheet_context="")
    return AgentResult(requested, "claude", "bedrock", models.BEDROCK_MODEL_ID, answer, fallback=fallback)


def delegate(chat_id: int, value: str, *, bedrock_fallback=None) -> AgentResult:
    requested, task = parse_delegate(value)
    if not task:
        raise ValueError("اكتب المهمة بعد /delegate")

    if contains_private_data(task):
        if requested in {"gpt", "gemini"}:
            raise ValueError("المهمة تحتوي بيانات خاصة؛ لا يمكن إرسالها إلى وكيل خارجي. استخدم Claude/Bedrock أو أزل المعرّفات.")
        return _bedrock_manager(chat_id, task, bedrock_fallback, requested=requested, fallback=False)

    selected = choose_agent(task) if requested == "auto" else requested
    if selected not in ROLE_MODELS:
        raise ValueError("الوكيل غير معروف. استخدم auto أو claude أو gpt أو gemini")

    try:
        return _openrouter_agent(selected, task)
    except Exception:
        # Automatic delegation should remain useful when OpenRouter is unavailable.
        # Named GPT/Gemini requests must not silently impersonate another model.
        if requested == "auto" or selected == "claude":
            return _bedrock_manager(chat_id, task, bedrock_fallback, requested=requested, fallback=True)
        raise


def agents_status_text() -> str:
    status = models.status()
    configured = status["openrouter_configured"]
    bedrock = status["bedrock_configured"]
    return "\n".join([
        "🧠 AI Team v0.6",
        f"Claude — Manager: {status['models']['manager']}",
        f"GPT — Critic: {status['models']['critic']}",
        f"Gemini — Researcher: {status['models']['google']}",
        f"OpenRouter: {'configured ✅' if configured else 'not configured'}",
        f"Bedrock protected manager/fallback: {'configured ✅' if bedrock else 'not configured'}",
        "Auto routing: Research→Gemini | Review/Risk→GPT | Management→Claude",
        "Tools: model reasoning only; web/Instagram research connector is the next stage.",
    ])


def council(chat_id: int, question: str, *, bedrock_fallback=None) -> str:
    task = (question or "").strip()
    if not task:
        raise ValueError("اكتب السؤال بعد /council")
    if contains_private_data(task):
        raise ValueError("AI Council لا يستقبل بيانات مريض أو معرّفات خاصة. أزل البيانات الخاصة أولًا.")

    answers: list[tuple[str, str, str]] = []
    failures: list[str] = []
    for agent in ("claude", "gpt", "gemini"):
        try:
            result = _openrouter_agent(agent, task)
            answers.append((agent, result.model, result.answer))
        except Exception as exc:  # diagnostic boundary; never include credentials
            failures.append(f"{ROLE_LABELS[agent]}: {models._safe_error(exc)}")

    if len(answers) < 2:
        if bedrock_fallback is None:
            raise RuntimeError("AI Council unavailable: fewer than two advisers responded")
        fallback = _bedrock_manager(
            chat_id,
            "The multi-agent council could not obtain two independent responses. Give a single-manager assessment and explicitly state that the council was unavailable.\n\n" + task,
            bedrock_fallback,
            requested="council",
            fallback=True,
        )
        detail = "\n".join(failures[:3])
        return f"⚠️ AI Council unavailable; Bedrock manager fallback used.\n{fallback.answer}\n\nTechnical status:\n{detail}"

    evidence = "\n\n".join(
        f"[{ROLE_LABELS[a]} | {m}]\n{answer}" for a, m, answer in answers
    )
    judge_prompt = (
        "Act as the council judge. Synthesize the independent adviser notes below. "
        "Return: consensus, disagreements, key risk/blind spot, recommendation, and confidence 0-100. "
        "Do not invent external evidence.\n\nQUESTION:\n" + task + "\n\nADVISERS:\n" + evidence
    )
    try:
        judge = _openrouter_agent("claude", judge_prompt).answer
        judge_source = "Claude judge"
    except Exception:
        fallback = _bedrock_manager(chat_id, judge_prompt, bedrock_fallback, requested="council", fallback=True)
        judge = fallback.answer
        judge_source = "Bedrock judge fallback"

    failures_note = ("\n\nUnavailable adviser(s):\n" + "\n".join(failures)) if failures else ""
    return f"🧠 AI Council — {len(answers)}/3 advisers\nJudge: {judge_source}\n\n{judge}{failures_note}"

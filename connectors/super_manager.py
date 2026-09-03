# -*- coding: utf-8 -*-
"""Super Manager v1 — evidence-grounded Chief-of-Staff reasoning for Abdulrahman.

This module is intentionally reasoning-only. It may read bounded operational context,
but it never creates Calendar events, sends outbound messages, or mutates operational
records. External effects stay behind the existing preview/approval/confirm paths.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from connectors import lean_missions as lean
from connectors import model_gateway as models
from connectors import ops_context
from connectors import strategic_creator
from connectors import task_delegation as base

VERSION = "v1.1"
MAX_STATE_CHARS = max(800, int(os.environ.get("SUPER_MANAGER_STATE_CONTEXT_CHARS", "3200")))
MAX_OPS_CHARS = max(800, int(os.environ.get("SUPER_MANAGER_OPS_CONTEXT_CHARS", "2800")))
MAX_TOKENS = max(500, int(os.environ.get("SUPER_MANAGER_MAX_TOKENS", "1000")))

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_URL_RE = re.compile(r"https?://\S+", re.I)
_IDENTIFIER_RE = re.compile(
    r"(?i)(mrn|medical\s*record|رقم\s*الملف|رقم\s*الهوية|هوية\s*المريض)\s*[:#-]?\s*[A-Z0-9-]+"
)
_SENSITIVE_RE = re.compile(r"patient|مريض|diagnosis|تشخيص|mrn|medical\s*record|رقم\s*الملف", re.I)

THINKING_CONTRACT = """
ROLE
You are Abdulrahman's Chief of Staff, not an archive. Your job is to convert supplied evidence into management judgment.

EVIDENCE DISCIPLINE
- Never invent a date, owner, approver, dependency, number, event, history, or authority.
- Label material claims as CONFIRMED, INFERENCE, or NEEDS_INPUT.
- INFERENCE must name the evidence that supports it.
- Unknown execution-critical fields are NEEDS_INPUT. Ask one blocking question, not a questionnaire.
- Do not claim that you performed an external action. Calendar, messages, and record mutations require proposal -> preview -> approval -> execution.
- WO-8 record_links are authoritative only at their recorded status: BLOCKED_BY/CONFIRMED may be treated as a confirmed dependency; POSSIBLE_DEPENDENCY/NEEDS_INPUT must remain an inference/question.

C1 LINK BEFORE ANSWERING
Check whether the request is blocked by an open waiting item, depends on unfinished work, conflicts with a confirmed appointment, or connects to a current project/decision. Use shared intake_id/relation_group_id and record_links when supplied. A blocked execution decision must be described as blocked, not treated as freely executable.

C2 SURFACE THE UNSAID
For a new commitment, check owner, deadline, approver, dependency, and success criterion. Surface only the single missing field that most blocks execution.

C3 MAKE THE DECISION DECIDABLE
Turn vague A-or-B choices into a decision criterion: what condition must be true for option A to be viable?

C4 SEARCH FOR A THIRD OPTION
When useful, propose a realistic third option such as partial launch, staged scope, pilot, or scope change. If no defensible third option exists, say so; never invent one just to fill the format.

C5 RECOMMEND
Give an explicit recommendation and rationale. If evidence is weak, state low confidence rather than hiding behind neutrality.

C6 DETECT PATTERNS
Call something a PATTERN only when at least three comparable historical records are present in supplied evidence. Otherwise say PATTERN: NOT_ENOUGH_EVIDENCE.

SAUDI OPERATING CONTEXT
- Default timezone is Asia/Riyadh.
- Normal workweek context is Sunday-Thursday; Friday-Saturday are weekend days.
- Do not assume institutional approval lead times. Use recorded evidence or NEEDS_INPUT.
- Ramadan/Eid effects may matter only when a verified calendar/source places the date in that period.
- A decision requiring higher approval can still have a recommendation, but execution is BLOCKED_BY_APPROVAL until approval is confirmed.

CLINICAL BOUNDARY
For clinical matters, you are decision support, not clinical authority. Use hypothesis / needs confirmation / test-retest language and do not autonomously execute clinical decisions.
""".strip()

OUTPUT_CONTRACT = """
Return SUPER_MANAGER_PACKET only, concise but substantive:
SITUATION: one sentence
CONFIRMED: up to 4 bullets grounded in supplied evidence
INFERENCE: up to 3 bullets; each must cite the evidence basis in plain words
DEPENDENCIES: blockers/waiting links, or NONE
DECISION_CRITERION: one measurable/observable condition, or NONE
OPTIONS: A, B, and C only if C is genuinely useful
RECOMMENDATION: explicit recommendation + why
NEEDS_INPUT: exactly one blocking question, or NONE
NEXT: up to 3 ordered next actions; unknown owner/date must be written NEEDS_INPUT
APPROVAL: NONE or the exact external effect/decision needing approval
PATTERN: named pattern only with >=3 comparable supplied records; otherwise NOT_ENOUGH_EVIDENCE
CONFIDENCE: 0-100 + one short reason
""".strip()


@dataclass
class ManagerContext:
    text: str = ""
    sources: tuple[str, ...] = ()
    state_rows: int = 0
    ops_rows: int = 0
    errors: tuple[str, ...] = ()


def _clean(value, limit: int = 220) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = _IDENTIFIER_RE.sub(r"\1: [IDENTIFIER_REDACTED]", text)
    text = _PHONE_RE.sub("[PHONE_REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = _URL_RE.sub("[LINK_OMITTED]", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _record_line(section: str, row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    link_keys = ("record_id", "intake_id", "relation_group_id", "record_type")
    preferred = {
        "tasks": link_keys + ("id", "task_id", "title", "العنوان", "المهمة", "status", "الحالة", "owner", "المالك", "due_date", "الموعد", "next_step"),
        "projects": ("id", "project_id", "Project_ID", "المشروع", "اسم المشروع", "status", "الحالة", "phase", "المرحلة", "next", "الخطوة التالية"),
        "waiting_for": link_keys + ("wid", "task", "item", "project_id", "expected_from", "expected_by", "follow_up_date", "status"),
        "decision_requests": ("id", "project", "title", "deadline", "status"),
        "decisions": link_keys + ("التاريخ", "القرار", "الخيار", "الحالة", "decision_criterion", "review_date", "تاريخ المراجعة"),
        "action_queue": link_keys + ("action_id", "type", "status", "raw_temporal_text", "resolved_start", "approval_required"),
        "record_links": ("relation_id", "intake_id", "relation_group_id", "source_record_id", "target_record_id", "relation", "status", "basis"),
    }
    values = []
    for key in preferred.get(section, ()):
        value = row.get(key)
        if value not in (None, "", []):
            values.append(f"{key}={_clean(value, 140)}")
    if not values:
        for key, value in list(row.items())[:6]:
            if value not in (None, "", []):
                values.append(f"{_clean(key, 50)}={_clean(value, 120)}")
    line = " | ".join(values)
    if _SENSITIVE_RE.search(line):
        return ""
    return f"STATE {section} | {line}" if line else ""


def _state_context() -> tuple[str, int, str | None]:
    try:
        from engine.store import Store

        state = Store().rows_all()
    except Exception as exc:
        return "", 0, models._safe_error(exc)[:180]

    lines = []
    # WO-8 links and newly captured records are appended, so read the most recent
    # rows rather than the oldest rows. Links come first so C1 sees relationship
    # evidence before individual record detail if the context limit is reached.
    for section in (
        "record_links", "waiting_for", "decisions", "decision_requests",
        "projects", "tasks", "action_queue",
    ):
        rows = state.get(section) or []
        for row in rows[-8:]:
            line = _record_line(section, row)
            if line:
                lines.append(line)
            if len(lines) >= 28:
                break
        if len(lines) >= 28:
            break
    text = "\n".join(lines)
    if len(text) > MAX_STATE_CHARS:
        text = text[: MAX_STATE_CHARS - 30].rstrip() + "\n[STATE_CONTEXT_TRUNCATED]"
    return text, len(lines), None


def build_context(goal: str) -> ManagerContext:
    chunks = []
    sources = []
    errors = []

    state_text, state_rows, state_error = _state_context()
    if state_text:
        chunks.append("STATESTORE_CONTEXT (read-only evidence):\n" + state_text)
        sources.append("state")
    if state_error:
        errors.append("state: " + state_error)

    try:
        packet = ops_context.build_ops_context(goal, limit_chars=MAX_OPS_CHARS)
        ops_text = packet.text
        if ops_text:
            chunks.append("GOOGLE_OPS_CONTEXT (read-only evidence):\n" + ops_text)
            sources.extend(x for x in packet.sources if x not in sources)
        errors.extend(packet.errors)
        ops_rows = packet.calendar_count + packet.sheet_count
    except Exception as exc:
        ops_rows = 0
        errors.append("ops: " + models._safe_error(exc)[:180])

    return ManagerContext(
        text="\n\n".join(chunks),
        sources=tuple(sources),
        state_rows=state_rows,
        ops_rows=ops_rows,
        errors=tuple(errors[:4]),
    )


def build_prompt(goal: str, context: ManagerContext) -> str:
    evidence = context.text or "NO_OPERATIONAL_CONTEXT_AVAILABLE"
    strategic_overlay = strategic_creator.build_overlay(goal)
    strategic_section = (
        "\n\n" + strategic_overlay
        if strategic_overlay
        else ""
    )
    return (
        THINKING_CONTRACT
        + strategic_section
        + "\n\nUSER_REQUEST:\n" + goal.strip()
        + "\n\nSUPPLIED_EVIDENCE:\n" + evidence
        + "\n\n" + OUTPUT_CONTRACT
    )


def manager(chat_id: int, objective: str, *, bedrock_fallback=None) -> str:
    goal = (objective or "").strip()
    if not goal:
        raise ValueError("اكتب الطلب بعد /manager")
    if base.contains_private_data(goal):
        raise ValueError(
            "طلب /manager يحتوي معرّفات خاصة. أزل المعرّفات أو استخدم المسار السريري المحمي."
        )

    context = build_context(goal)
    prompt = build_prompt(goal, context)
    answer, provider, model, usage = lean._bedrock_manager(
        prompt,
        max_tokens=MAX_TOKENS,
        chat_id=chat_id,
        bedrock_fallback=bedrock_fallback,
    )
    usage = usage or {}
    sources = "+".join(context.sources) if context.sources else "none"
    warning = ""
    if context.errors:
        warning = "\nContext warning: " + " | ".join(context.errors[:2])
    return (
        f"🧠 Super Manager {VERSION}\n"
        f"Route: {provider}:{model}\n"
        f"Context: {sources} | state_rows={context.state_rows} ops_rows={context.ops_rows}"
        f"{warning}\n\n{answer}"
    )


def shadow(chat_id: int, objective: str, *, bedrock_fallback=None) -> str:
    """Compare current Mission behavior with Super Manager v1; no external effects."""
    goal = (objective or "").strip()
    if not goal:
        raise ValueError("اكتب الطلب بعد /manager_shadow")
    legacy = base.mission(chat_id, goal, bedrock_fallback=bedrock_fallback)
    candidate = manager(chat_id, goal, bedrock_fallback=bedrock_fallback)
    return (
        "🧪 MANAGER SHADOW — no external actions\n\n"
        "===== LEGACY / MISSION =====\n"
        + legacy
        + "\n\n===== SUPER MANAGER v1 =====\n"
        + candidate
    )


def status_text() -> str:
    mode = os.environ.get("AI_SUPER_MANAGER_DEFAULT", "0").strip()
    return (
        f"🧠 Super Manager {VERSION}\n"
        f"Default natural-text routing: {'ON' if mode == '1' else 'OFF'}\n"
        "Commands: /manager, /manager_shadow\n"
        "External effects: approval-gated / not executed by this module\n"
        "Thinking: C1-C6 + CONFIRMED/INFERENCE/NEEDS_INPUT + WO-8 record_links"
    )

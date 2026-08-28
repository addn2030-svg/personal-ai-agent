# -*- coding: utf-8 -*-
"""On-demand operational context capsule for lean missions.

This module keeps token use small by loading operational evidence only when the
objective explicitly depends on today's/tomorrow's schedule or current priorities.
It never loads conversation history. Calendar IDs/links are omitted. Sheet rows
that look clinical/private are skipped before reaching a model.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from . import lean_missions as lean
from . import task_delegation as base

OPS_CONTEXT_LIMIT = int(os.environ.get("MISSION_OPS_CONTEXT_CHARS", "2400"))
OPS_SHEET_TABS = (
    "Projects",
    "خطة الإنجاز والمهام",
    "Waiting_For",
    "Blockers",
    "Executive_Brief",
)

_TRIGGER_RE = re.compile(
    r"\b(today|tomorrow|priority|priorities|task|tasks|calendar|meeting|meetings|pending|deadline|deadlines)\b|"
    r"اليوم|غد[ًاا]?|بكره|بكرة|أولوية|اولويه|أولويات|اولويات|مهام|مهمة|جدول|موعد|مواعيد|اجتماع|اجتماعات|معلق|متابعة|موعد نهائي",
    re.I,
)
_SENSITIVE_RE = re.compile(
    r"patient|مريض|mrn|medical\s*record|رقم\s*الملف|رقم\s*الهوية|diagnosis|تشخيص|"
    r"\b(?:\+?966|0)?5\d{8}\b|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.I,
)
_MRN_RE = re.compile(r"(?i)(mrn|medical record|رقم الملف|رقم الهوية)\s*[:#-]?\s*[A-Z0-9-]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_STATE = threading.local()


@dataclass
class OpsContextPacket:
    text: str = ""
    sources: tuple[str, ...] = ()


def needs_ops_context(goal: str) -> bool:
    return bool(_TRIGGER_RE.search(goal or ""))


def _clean(value: str, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = _MRN_RE.sub(r"\1: [IDENTIFIER_REDACTED]", text)
    text = _PHONE_RE.sub("[PHONE_REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _calendar_lines(goal: str) -> list[str]:
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip() and not os.environ.get(
        "GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON", ""
    ).strip():
        return []
    from . import calendar_actions

    rows = calendar_actions.list_events(days_forward=2, max_results=12)
    now = calendar_actions.now_local()
    target = None
    if re.search(r"tomorrow|غد[ًاا]?|بكره|بكرة", goal or "", re.I):
        target = now.date() + __import__("datetime").timedelta(days=1)
    elif re.search(r"today|اليوم", goal or "", re.I):
        target = now.date()

    lines = []
    for row in rows:
        raw = str(row.get("start", ""))
        shown = raw
        event_date = None
        try:
            if "T" in raw:
                parsed = __import__("datetime").datetime.fromisoformat(raw.replace("Z", "+00:00"))
                parsed = parsed.astimezone(calendar_actions.TZ)
                event_date = parsed.date()
                shown = parsed.strftime("%Y-%m-%d %H:%M")
            else:
                event_date = __import__("datetime").date.fromisoformat(raw)
        except Exception:
            pass
        if target is not None and event_date is not None and event_date != target:
            continue
        title = _clean(row.get("title", "(بدون عنوان)"), 120)
        if _SENSITIVE_RE.search(title):
            continue
        lines.append(f"CAL {shown} | {title}")
        if len(lines) >= 8:
            break
    return lines


def _sheet_lines() -> list[str]:
    from . import sheet_intelligence

    if not sheet_intelligence.configured():
        return []
    data = sheet_intelligence.snapshot(max_rows=12, max_cols=8)
    lines: list[str] = []
    for tab in OPS_SHEET_TABS:
        rows = data.get(tab) or []
        for idx, row in enumerate(rows[:8], 1):
            raw = " | ".join(str(cell) for cell in row)
            if _SENSITIVE_RE.search(raw):
                continue
            clean = " | ".join(_clean(cell, 120) for cell in row if str(cell).strip())
            if clean:
                lines.append(f"SHEET {tab} r{idx} | {clean}")
            if len(lines) >= 14:
                return lines
    return lines


def build_ops_context(goal: str, limit_chars: int = OPS_CONTEXT_LIMIT) -> OpsContextPacket:
    if not needs_ops_context(goal):
        return OpsContextPacket()

    lines: list[str] = []
    sources: list[str] = []
    try:
        cal = _calendar_lines(goal)
        if cal:
            lines.extend(cal)
            sources.append("calendar")
    except Exception:
        pass
    try:
        sheets = _sheet_lines()
        if sheets:
            lines.extend(sheets)
            sources.append("sheets")
    except Exception:
        pass

    text = "\n".join(lines).strip()
    if len(text) > max(400, int(limit_chars)):
        text = text[: max(360, int(limit_chars) - 40)].rstrip() + "\n[OPS_CONTEXT_TRUNCATED]"
    return OpsContextPacket(text=text, sources=tuple(sources))


def _install_manager_prompt() -> None:
    if getattr(lean, "_ops_context_prompt_installed", False):
        return
    original = lean._manager_prompt

    def wrapped(goal: str, specialist: str = "", critic: str = "", capsule: str = "") -> str:
        packet = build_ops_context(goal)
        _STATE.packet = packet
        prompt = original(goal, specialist, critic, capsule)
        if not packet.text:
            return prompt
        return (
            prompt
            + "\n\nOPS_CONTEXT_CAPSULE (read-only evidence; use only what is relevant):\n"
            + packet.text
        )

    lean._manager_prompt = wrapped
    lean._ops_context_prompt_installed = True


def mission(chat_id: int, objective: str, *, bedrock_fallback=None) -> str:
    _STATE.packet = OpsContextPacket()
    result = _ORIGINAL_MISSION(chat_id, objective, bedrock_fallback=bedrock_fallback)
    packet = getattr(_STATE, "packet", OpsContextPacket())
    if not packet.text:
        return result
    source_text = "+".join(packet.sources) if packet.sources else "none"
    lines = result.splitlines()
    insert_at = 2 if len(lines) >= 2 else len(lines)
    lines.insert(insert_at, f"Context: ops-mini | sources={source_text} | chars={len(packet.text)}")
    return "\n".join(lines)


def install() -> None:
    global _ORIGINAL_MISSION
    if getattr(base, "_ops_context_v093_installed", False):
        return
    _install_manager_prompt()
    _ORIGINAL_MISSION = lean.mission
    lean.mission = mission
    base.mission = mission
    base._ops_context_v093_installed = True


_ORIGINAL_MISSION = lean.mission

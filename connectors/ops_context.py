# -*- coding: utf-8 -*-
"""On-demand operational context capsule for lean missions.

This module keeps token use small by loading operational evidence only when the
objective explicitly depends on today's/tomorrow's schedule or current priorities.
It never loads conversation history. Calendar IDs/links are omitted. Sheet rows
that look clinical/private are skipped before reaching a model.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass

from . import lean_missions as lean
from . import model_gateway as models
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
_URL_RE = re.compile(r"https?://\S+", re.I)
_STATE = threading.local()


@dataclass
class OpsContextPacket:
    text: str = ""
    sources: tuple[str, ...] = ()
    triggered: bool = False
    calendar_count: int = 0
    sheet_count: int = 0
    errors: tuple[str, ...] = ()


def needs_ops_context(goal: str) -> bool:
    return bool(_TRIGGER_RE.search(goal or ""))


def _clean(value: str, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = _MRN_RE.sub(r"\1: [IDENTIFIER_REDACTED]", text)
    text = _PHONE_RE.sub("[PHONE_REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _safe_http_error(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None) or getattr(exc, "code", None)
    reason = ""
    message = ""
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8", errors="replace")
        except Exception:
            content = ""
    if content:
        try:
            payload = json.loads(content)
            error = payload.get("error") or {}
            message = str(error.get("message") or "")
            errors = error.get("errors") or []
            if errors and isinstance(errors[0], dict):
                reason = str(errors[0].get("reason") or "")
            if not reason:
                details = error.get("details") or []
                for item in details:
                    if isinstance(item, dict) and item.get("reason"):
                        reason = str(item.get("reason"))
                        break
        except Exception:
            pass
    if not message:
        message = str(getattr(exc, "reason", "") or "")
    message = _URL_RE.sub("[link omitted]", message)
    message = _EMAIL_RE.sub("[EMAIL_REDACTED]", message)
    message = re.sub(r"\s+", " ", message).strip()[:220]
    parts = []
    if status:
        parts.append(f"HTTP {status}")
    if reason:
        parts.append(f"reason={reason[:80]}")
    if message:
        parts.append(f"message={message}")
    return " ".join(parts)


def _runtime_hint(source: str) -> str:
    try:
        if source == "calendar":
            from . import calendar_actions
            state = calendar_actions.calendar_auth_status()
            credential = "valid" if state.get("service_account_valid") else (
                "invalid" if state.get("service_account_present") else "missing"
            )
            return (
                f"auth={state.get('path', 'unknown')},calendar_id={state.get('calendar_id_mode', 'unknown')},"
                f"credential={credential}"
            )
        if source == "sheets":
            from . import google_credentials, sheet_intelligence
            cred = google_credentials.status()
            credential = "valid" if cred.get("valid") else ("invalid" if cred.get("present") else "missing")
            return (
                f"sheet_id={'yes' if bool(sheet_intelligence.SHEET_ID) else 'no'},credential={credential},"
                f"direct={'yes' if sheet_intelligence._direct_ready() else 'no'},"
                f"webhook={'yes' if sheet_intelligence._webhook_ready() else 'no'}"
            )
    except Exception:
        return "runtime=unknown"
    return "runtime=unknown"


def _safe_source_error(source: str, exc: Exception) -> str:
    detail = _safe_http_error(exc) or models._safe_error(exc)[:220]
    return f"{source}: {detail} | {_runtime_hint(source)}"[:520]


def _calendar_lines(goal: str) -> list[str]:
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
    errors: list[str] = []
    calendar_count = 0
    sheet_count = 0

    try:
        cal = _calendar_lines(goal)
        calendar_count = len(cal)
        if cal:
            lines.extend(cal)
            sources.append("calendar")
    except Exception as exc:
        errors.append(_safe_source_error("calendar", exc))

    try:
        sheets = _sheet_lines()
        sheet_count = len(sheets)
        if sheets:
            lines.extend(sheets)
            sources.append("sheets")
    except Exception as exc:
        errors.append(_safe_source_error("sheets", exc))

    text = "\n".join(lines).strip()
    if len(text) > max(400, int(limit_chars)):
        text = text[: max(360, int(limit_chars) - 40)].rstrip() + "\n[OPS_CONTEXT_TRUNCATED]"
    return OpsContextPacket(
        text=text,
        sources=tuple(sources),
        triggered=True,
        calendar_count=calendar_count,
        sheet_count=sheet_count,
        errors=tuple(errors),
    )


def probe(goal: str = "priorities tomorrow") -> dict:
    """Read-only context diagnostic. It performs no model inference."""
    packet = build_ops_context(goal)
    return {
        "triggered": packet.triggered,
        "sources": list(packet.sources),
        "chars": len(packet.text),
        "calendar_rows": packet.calendar_count,
        "sheet_rows": packet.sheet_count,
        "errors": list(packet.errors),
        "preview": packet.text[:1200],
    }


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
    if not packet.triggered:
        return result

    source_text = "+".join(packet.sources) if packet.sources else "none"
    if packet.text:
        status = "ready"
    elif packet.errors:
        status = "source-error"
    else:
        status = "empty"
    lines = result.splitlines()
    insert_at = 2 if len(lines) >= 2 else len(lines)
    lines.insert(
        insert_at,
        f"Context: ops-mini | status={status} | sources={source_text} | "
        f"calendar={packet.calendar_count} sheets={packet.sheet_count} | chars={len(packet.text)}",
    )
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

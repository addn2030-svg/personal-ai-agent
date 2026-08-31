# -*- coding: utf-8 -*-
"""Executive-signal discovery for briefs.

This module deliberately detects durable management context that is easy to miss when
only TASK/DECISION keywords are considered: operating constraints, logistics rules,
commitments, decision criteria, financial boundaries, and capability/status changes.

It is read-only. It never creates tasks, Calendar events, reminders, or external actions.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Iterable

from engine.store import Store

PRIVATE_PLACEHOLDER = "[REDACTED_FROM_PERSONAL_OS]"
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_ARRIVAL_RE = re.compile(
    r"(?:الوصول|أصل|اصل|arriv(?:e|al)|reach).*?(?:قبل|بحلول|by)\s*"
    r"(?P<time>(?:[01]?\d|2[0-3]):[0-5]\d)",
    re.I,
)
_PRIVATE_RE = re.compile(
    r"patient|مريض|diagnosis|تشخيص|mrn|medical\s*record|رقم\s*الملف|رقم\s*الهوية|هوية\s*المريض",
    re.I,
)

_SIGNAL_RULES = (
    (
        "LOGISTICS_RULE",
        4,
        re.compile(
            r"الوصول|الانطلاق|مدة\s*الطريق|وقت\s*الطريق|المشوار|التنقل|"
            r"arriv(?:e|al)|depart(?:ure)?|travel\s*time|route\s*duration|commute",
            re.I,
        ),
    ),
    (
        "HARD_CONSTRAINT",
        3,
        re.compile(
            r"(?:^|\s)(?:يجب|لازم|لابد|لا\s*بد|ممنوع|يشترط|شرط|حد\s*أقصى|"
            r"قبل|بحلول|must|required|no\s+later\s+than|deadline|by)(?:\s|$)",
            re.I,
        ),
    ),
    (
        "COMMITMENT",
        3,
        re.compile(r"اتفقنا|تم\s*الاتفاق|ملتزم|التزام|سأقوم|سوف\s+أقوم|وعد|agreed|commit(?:ted|ment)?", re.I),
    ),
    (
        "DECISION_CRITERION",
        2,
        re.compile(r"يعتمد\s+على|في\s+حال|إذا|اذا|بشرط|معيار|criterion|depends\s+on|provided\s+that", re.I),
    ),
    (
        "FINANCIAL_BOUNDARY",
        3,
        re.compile(
            r"(?:\bSAR\b|ريال|ر\.س|ميزانية|تكلفة|سعر|حد\s*مالي|تمويل|دفع|رسوم|"
            r"budget|cost|price|payment|funding)",
            re.I,
        ),
    ),
    (
        "CAPABILITY_STATUS",
        2,
        re.compile(
            r"تم\s*ربط|تم\s*تفعيل|يعمل|جاهز|متصل|غير\s*متاح|تعطل|متوقف|"
            r"connected|enabled|ready|unavailable|failed|down|deployed|live",
            re.I,
        ),
    ),
    (
        "OPPORTUNITY_OR_RISK",
        2,
        re.compile(r"فرصة|مخاطر|خطر|تعثر|تحسين|opportunit|risk|blocker|improvement", re.I),
    ),
)


def _clean(text: str, limit: int = 500) -> str:
    value = str(text or "").translate(_AR_DIGITS).replace("\n", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:limit]


def _arrival_rule(text: str) -> dict:
    value = _clean(text)
    match = _ARRIVAL_RE.search(value)
    if not match:
        return {}
    target = match.group("time")
    if len(target.split(":", 1)[0]) == 1:
        target = "0" + target
    route_based = bool(re.search(r"مدة\s*الطريق|وقت\s*الطريق|travel\s*time|route\s*duration", value, re.I))
    result = {
        "arrival_target": target,
        "departure_rule": f"departure_time = {target} - live_route_duration",
        "requires_live_route_duration": route_based,
    }
    return result


def calculate_departure(arrival_target: str, travel_minutes: int) -> dict:
    """Calculate a departure clock from a confirmed target and route duration.

    No buffer is added because a buffer must be explicitly supplied by policy/evidence.
    """
    normalized = _clean(arrival_target, 10)
    match = _TIME_RE.fullmatch(normalized)
    if not match:
        raise ValueError("arrival_target must be HH:MM")
    minutes = int(travel_minutes)
    if minutes < 0 or minutes > 24 * 60:
        raise ValueError("travel_minutes must be between 0 and 1440")
    base = dt.datetime(2000, 1, 2, int(match.group(1)), int(match.group(2)))
    departure = base - dt.timedelta(minutes=minutes)
    return {
        "time": departure.strftime("%H:%M"),
        "day_offset": (departure.date() - base.date()).days,
        "travel_minutes": minutes,
    }


def detect_signals(
    text: str,
    *,
    source_ref: str = "",
    evidence_status: str = "OBSERVED_INPUT",
    source_type: str = "text",
) -> list[dict]:
    value = _clean(text)
    if len(value) < 6 or value == PRIVATE_PLACEHOLDER or _PRIVATE_RE.search(value):
        return []

    hits = []
    for category, weight, rx in _SIGNAL_RULES:
        if rx.search(value):
            hits.append((category, weight))

    explicit_time = bool(_TIME_RE.search(value))
    recurring = bool(re.search(r"يومي|يوميا|أسبوع|شهري|كل\s+يوم|كل\s+أسبوع|daily|weekly|monthly", value, re.I))
    score = sum(weight for _, weight in hits)
    if explicit_time:
        score += 1
    if recurring:
        score += 1

    # Require either one high-specificity signal or corroborating evidence. This avoids
    # treating generic conversational text as executive context merely because it says "إذا".
    if not hits or (score < 3 and max((w for _, w in hits), default=0) < 3):
        return []

    categories = []
    for category, _ in hits:
        if category not in categories:
            categories.append(category)

    primary = categories[0]
    signal = {
        "category": primary,
        "categories": categories,
        "score": score,
        "text": value,
        "source_ref": source_ref,
        "source_type": source_type,
        "evidence_status": evidence_status,
    }
    arrival = _arrival_rule(value)
    if arrival:
        signal["logistics"] = arrival
    return [signal]


def detect_row_signals(items: Iterable[dict], *, limit: int = 25) -> list[dict]:
    found = []
    for item in items:
        text = " | ".join(str(x) for x in (item.get("values") or []))
        source_ref = f"sheet:{item.get('sheet', '?')}:row:{item.get('row', '?')}"
        for signal in detect_signals(
            text,
            source_ref=source_ref,
            evidence_status="SHEET_EVIDENCE",
            source_type="sheet_row",
        ):
            signal["sheet"] = item.get("sheet")
            signal["row"] = item.get("row")
            found.append(signal)
    return _dedupe(found)[:limit]


def _fact_text(row: dict) -> str:
    subject = _clean(row.get("subject", ""), 120)
    predicate = _clean(row.get("predicate", ""), 120)
    value = _clean(row.get("value", ""), 400)
    return " | ".join(x for x in (subject, predicate, value) if x)


def _dedupe(signals: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for signal in sorted(signals, key=lambda x: int(x.get("score", 0)), reverse=True):
        key = re.sub(r"\W+", "", str(signal.get("text", "")).lower())[:180]
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result


def state_signals(*, limit: int = 25) -> list[dict]:
    """Read bounded non-sensitive StateStore evidence for Executive Brief context."""
    try:
        state = Store().rows_all()
    except Exception:
        return []

    found = []
    for row in (state.get("fact_registry") or [])[-40:]:
        text = _fact_text(row)
        found.extend(detect_signals(
            text,
            source_ref=str(row.get("source_ref") or row.get("fact_id") or "state:fact_registry"),
            evidence_status=str(row.get("verification_status") or "CONFIRMED_FACT"),
            source_type="fact_registry",
        ))

    # Recent inbox messages are evidence of what the owner said, but they are not silently
    # promoted to durable facts. The brief must preserve OBSERVED_INPUT as its status.
    for row in (state.get("unified_inbox") or [])[-60:]:
        if row.get("sensitive") or str(row.get("content", "")) == PRIVATE_PLACEHOLDER:
            continue
        content = str(row.get("content") or "")
        source_ref = str(row.get("source_ref") or row.get("id") or "state:unified_inbox")
        status = "USER_INPUT" if str(row.get("source", "")).upper() == "TELEGRAM" else "OBSERVED_INPUT"
        found.extend(detect_signals(
            content,
            source_ref=source_ref,
            evidence_status=status,
            source_type="unified_inbox",
        ))

    return _dedupe(found)[:limit]


def compact_state_signals(*, limit_chars: int = 7000) -> str:
    return json.dumps(state_signals(), ensure_ascii=False, separators=(",", ":"))[:limit_chars]

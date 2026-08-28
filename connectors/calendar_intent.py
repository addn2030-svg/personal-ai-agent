# -*- coding: utf-8 -*-
"""Natural-language Calendar routing for Telegram.

This adapter keeps Calendar writes behind the existing /confirm_event approval gate.
It routes explicit scheduling/reminder language to the deterministic Calendar
proposal flow, so general AI answers cannot incorrectly claim Calendar is absent.
"""
from __future__ import annotations

import datetime as dt
import re

from . import calendar_actions

_CALENDAR_ACTION_RE = re.compile(
    r"(?:\bremind\s+me\b|\badd\b.*\bcalendar\b|\bput\b.*\bcalendar\b|"
    r"\brecord\b.*\bcalendar\b|\bsave\b.*\bcalendar\b|^\s*schedule\b|"
    r"ذكرني|ذكّرني|أضف.*(?:التقويم|تقويم|موعد)|اضف.*(?:التقويم|تقويم|موعد)|"
    r"سجل.*(?:التقويم|تقويم|موعد)|سجّل.*(?:التقويم|تقويم|موعد))",
    re.I | re.S,
)
_RELATIVE_EN_RE = re.compile(
    r"\b(?:in|after)\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", re.I
)
_RELATIVE_AR_RE = re.compile(
    r"بعد\s+(\d+)\s*(دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات)", re.I
)
_DURATION_EN_RE = re.compile(
    r"\bfor\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", re.I
)
_DURATION_AR_RE = re.compile(
    r"(?:لمده|لمدة|مدة)\s*(\d+)\s*(دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات)", re.I
)

_ORIGINAL_PARSE = calendar_actions.parse_event_request
_ORIGINAL_HANDLE = None
_INSTALLED = False


def is_calendar_action(text: str) -> bool:
    value = str(text or "").strip()
    if not value or value.startswith("/"):
        return False
    return bool(_CALENDAR_ACTION_RE.search(value))


def routed_text(text: str) -> str:
    value = str(text or "").strip()
    return f"/remind {value}" if is_calendar_action(value) else value


def _minutes(amount: int, unit: str) -> int:
    return int(amount) * (60 if re.search(r"hour|hr|ساع", unit, re.I) else 1)


def _relative_offset(text: str) -> int | None:
    normalized = str(text or "").translate(calendar_actions.AR_DIGITS)
    match = _RELATIVE_EN_RE.search(normalized)
    if match:
        return _minutes(int(match.group(1)), match.group(2))
    match = _RELATIVE_AR_RE.search(normalized)
    if match:
        return _minutes(int(match.group(1)), match.group(2))
    return None


def _duration_minutes(text: str, default: int = 60) -> int:
    normalized = str(text or "").translate(calendar_actions.AR_DIGITS)
    match = _DURATION_EN_RE.search(normalized)
    if match:
        return max(1, min(1440, _minutes(int(match.group(1)), match.group(2))))
    match = _DURATION_AR_RE.search(normalized)
    if match:
        return max(1, min(1440, _minutes(int(match.group(1)), match.group(2))))
    return default


def _relative_title(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"^\s*/remind\s+", "", value, flags=re.I)
    value = re.sub(r"^\s*(?:remind\s+me|schedule)\s+", "", value, flags=re.I)
    value = re.sub(r"^\s*(?:ذكرني|ذكّرني|أضف|اضف|سجل|سجّل)\s+", "", value, flags=re.I)
    value = re.sub(r"\b(?:add|put|record|save)\b", "", value, flags=re.I)
    value = re.sub(r"\b(?:to|on|in)\s+(?:my\s+)?calendar\b", "", value, flags=re.I)
    value = re.sub(r"(?:إلى|الى|في)\s+(?:ال)?تقويم", "", value, flags=re.I)
    value = _RELATIVE_EN_RE.sub("", value)
    value = _RELATIVE_AR_RE.sub("", value)
    value = _DURATION_EN_RE.sub("", value)
    value = _DURATION_AR_RE.sub("", value)
    value = re.sub(r"\b(?:at\s+start|reminder\s+at\s+start)\b", "", value, flags=re.I)
    value = re.sub(r"^\s*to\s+", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -،,")
    return value or "تذكير"


def parse_event_request(text: str, base: dt.datetime | None = None):
    """Support relative scheduling while preserving the existing absolute parser."""
    offset = _relative_offset(text)
    if offset is None:
        return _ORIGINAL_PARSE(text, base=base)

    base = base or calendar_actions.now_local()
    if base.tzinfo is None:
        base = base.replace(tzinfo=calendar_actions.TZ)
    else:
        base = base.astimezone(calendar_actions.TZ)

    start = base + dt.timedelta(minutes=offset)
    default_duration = 10 if re.search(r"remind\s+me|ذكرني|ذكّرني", text, re.I) else 60
    duration = _duration_minutes(text, default=default_duration)

    # Relative reminders fire at event start by default. Explicit "before" wording
    # keeps the existing reminder parser.
    reminder = 0
    if re.search(r"قبل|\bbefore\b", text, re.I):
        reminder = calendar_actions._parse_reminder_minutes(text, default=0)

    return {
        "title": _relative_title(text),
        "start": start,
        "end": start + dt.timedelta(minutes=duration),
        "reminder_minutes": reminder,
        "timezone": calendar_actions.TZ_NAME,
    }


def install() -> None:
    """Install parser + Telegram intent routing once."""
    global _ORIGINAL_HANDLE, _INSTALLED
    if _INSTALLED:
        return

    calendar_actions.parse_event_request = parse_event_request

    from . import telegram_bot_legacy as legacy

    _ORIGINAL_HANDLE = legacy.handle_message

    def wrapped_handle_message(message: dict):
        text = (message.get("text") or message.get("caption") or "").strip()
        if text and is_calendar_action(text):
            routed = dict(message)
            routed["text"] = routed_text(text)
            routed.pop("caption", None)
            return _ORIGINAL_HANDLE(routed)
        return _ORIGINAL_HANDLE(message)

    legacy.handle_message = wrapped_handle_message
    _INSTALLED = True

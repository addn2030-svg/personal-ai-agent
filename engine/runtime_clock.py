# -*- coding: utf-8 -*-
"""Authoritative runtime clock for Abdulrahman AI OS.

Why this module exists
----------------------
The models behind the agent have no access to the server clock. Asked "what day
is it?", they answer from training priors and confidently name the wrong date.
Nothing in the prompt path ever anchored them to a real timestamp, so every
date, deadline, "tomorrow" and "next week" answer was a guess.

This module is the single source of truth for "now". It feeds two places:

* ``runtime_time_context()`` — a block injected into every model context, so the
  model can answer date/time questions from the live server instead of memory.
* ``status_text()`` — the instant ``/time`` Telegram reply, which is also the
  cheapest possible liveness probe: it touches no model and no Google API, so a
  reply proves the webhook process is alive and serving.

Timezone comes from ``MANAGER_TIMEZONE`` (default ``Asia/Riyadh``) and falls
back to a fixed UTC+03:00 offset when ``zoneinfo``/tzdata is unavailable, so a
missing tz database can never crash the production entrypoint.
"""
from __future__ import annotations

import datetime as dt
import os

TZ_ENV = "MANAGER_TIMEZONE"
DEFAULT_TZ_NAME = "Asia/Riyadh"
_FALLBACK_OFFSET = dt.timedelta(hours=3)  # Riyadh, no tzdata dependency

_AR_WEEKDAYS = {
    0: "الإثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

_EN_WEEKDAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


def tz_name() -> str:
    """Configured timezone name (``MANAGER_TIMEZONE``, default Asia/Riyadh)."""
    return (os.environ.get(TZ_ENV) or "").strip() or DEFAULT_TZ_NAME


def tz():
    """Resolved tzinfo, with a fixed Riyadh offset if the tz database is missing."""
    name = tz_name()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - tzdata missing or invalid override
        return dt.timezone(_FALLBACK_OFFSET, name)


def now() -> dt.datetime:
    """Current time in the configured runtime timezone."""
    return dt.datetime.now(tz())


def iso(moment: dt.datetime | None = None) -> str:
    moment = moment or now()
    return moment.isoformat(timespec="seconds")


def _offset_text(moment: dt.datetime) -> str:
    offset = moment.utcoffset() or dt.timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _weekday(moment: dt.datetime) -> str:
    return f"{_EN_WEEKDAYS[moment.weekday()]} / {_AR_WEEKDAYS[moment.weekday()]}"


def runtime_time_context(moment: dt.datetime | None = None) -> str:
    """Context block injected into every model prompt (Arabic/English)."""
    moment = moment or now()
    return (
        "RUNTIME CLOCK (authoritative — read from the live server, not from training data)\n"
        f"- Today (Gregorian): {moment:%Y-%m-%d} — {_weekday(moment)}\n"
        f"- Time now: {moment:%H:%M} (24-hour)\n"
        f"- Timezone: {tz_name()} ({_offset_text(moment)})\n"
        f"- ISO-8601: {moment.isoformat(timespec='seconds')}\n"
        "For today's date, the weekday, \"tomorrow\", \"next week\", deadlines or elapsed "
        "time, answer only from this block. Never substitute a date from training data. "
        "If this block is absent, say the current date cannot be determined."
    )


def status_text(moment: dt.datetime | None = None) -> str:
    """Arabic reply for the ``/time`` command — instant, model-free liveness probe."""
    moment = moment or now()
    return (
        f"🕒 وقت الخادم الآن: {moment:%Y-%m-%d} — {_AR_WEEKDAYS[moment.weekday()]} "
        f"— {moment:%H:%M}\n"
        f"المنطقة الزمنية: {tz_name()} ({_offset_text(moment)})\n"
        f"ISO: {moment.isoformat(timespec='seconds')}\n"
        "هذا الرد فوري من الخادم بدون نموذج ودون Google — وصوله يعني أن الوكيل يعمل."
    )

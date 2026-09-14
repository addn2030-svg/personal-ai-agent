# -*- coding: utf-8 -*-
"""Confirmed Google Calendar actions and Telegram reminder scheduling."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from . import google_credentials

TZ_NAME = os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh")
TZ = ZoneInfo(TZ_NAME)
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"
DATA_DIR = Path(os.environ.get("AI_OS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
LEDGER = DATA_DIR / "calendar-reminder-ledger.json"
AR_DAYS = {
    "الاثنين": 0, "الثلاثاء": 1, "الاربعاء": 2, "الأربعاء": 2,
    "الخميس": 3, "الجمعه": 4, "الجمعة": 4, "السبت": 5, "الاحد": 6, "الأحد": 6,
}
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_PERIODS = r"صباحا|صباحًا|صباح|ص|am|مساء|مساءً|م|pm"
class NeedsInputError(ValueError):
    """The request is recognized, but clarification is required before proposing a write."""

    code = "NEEDS_INPUT"

    def __init__(self, message: str):
        super().__init__(f"{self.code}: {message}")


_DATE_TOKEN_RE = re.compile(
    r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b"
    r"|\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b"
    r"|بعد\s+(?:غد|بكره)"
    r"|غد[ًاا]?|بكره|بكرة|tomorrow|اليوم|today"
    r"|(?:يوم\s+)?(?:" + "|".join(map(re.escape, AR_DAYS)) + r")",
    re.I,
)


def now_local():
    return dt.datetime.now(TZ)


def _next_weekday(base: dt.date, weekday: int) -> dt.date:
    days = (weekday - base.weekday()) % 7
    return base + dt.timedelta(days=days or 7)


def _date_value(token: str, base: dt.datetime) -> dt.date:
    value = token.strip().translate(AR_DIGITS)
    iso = re.fullmatch(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", value)
    if iso:
        try:
            return dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError as exc:
            raise NeedsInputError(
                f"التاريخ الصريح غير صالح ({value}). صححه بصيغة YYYY-MM-DD."
            ) from exc
    dmy = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if dmy:
        try:
            return dt.date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
        except ValueError as exc:
            raise NeedsInputError(
                f"التاريخ الصريح غير صالح ({value}). صححه بصيغة DD-MM-YYYY."
            ) from exc
    if re.fullmatch(r"بعد\s+(?:غد|بكره)", value, re.I):
        return base.date() + dt.timedelta(days=2)
    if re.fullmatch(r"غد[ًاا]?|بكره|بكرة|tomorrow", value, re.I):
        return base.date() + dt.timedelta(days=1)
    if re.fullmatch(r"اليوم|today", value, re.I):
        return base.date()
    day_name = re.sub(r"^يوم\s+", "", value).strip()
    if day_name in AR_DAYS:
        return _next_weekday(base.date(), AR_DAYS[day_name])
    raise ValueError("مرجع التاريخ غير صالح")


def _date_candidates(text: str, base: dt.datetime):
    normalized = text.translate(AR_DIGITS)
    rows = []
    for match in _DATE_TOKEN_RE.finditer(normalized):
        token = match.group(0)
        date_value = _date_value(token, base)
        rows.append({"text": token.strip(), "date": date_value, "span": match.span()})
    return rows


def _parse_date(text: str, base: dt.datetime) -> dt.date:
    candidates = _date_candidates(text, base)
    if not candidates:
        raise ValueError("حدد التاريخ: اليوم، غدًا، اسم اليوم، أو YYYY-MM-DD")

    # "اليوم الاثنين" is one date when the named weekday matches today.
    has_today = any(item["text"].strip().lower() in {"اليوم", "today"} for item in candidates)
    if has_today:
        for item in candidates:
            day_name = re.sub(r"^يوم\s+", "", item["text"]).strip()
            if AR_DAYS.get(day_name) == base.date().weekday():
                item["date"] = base.date()

    unique = []
    for item in candidates:
        if not any(row["date"] == item["date"] for row in unique):
            unique.append(item)
    if len(unique) > 1:
        refs = "، ".join(row["text"] for row in unique[:4])
        raise NeedsInputError(
            "وجدت أكثر من تاريخ محتمل (" + refs + "). "
            "اكتب موعدًا واحدًا فقط مع تاريخه ووقته."
        )
    return unique[0]["date"]


def _normalize_clock(hour: int, minute: int, period: str):
    period = (period or "").lower()
    if minute > 59 or hour > 23:
        raise NeedsInputError("الوقت غير صالح. استخدم ساعة بين 0 و23 ودقائق بين 00 و59.")
    if period and not 1 <= hour <= 12:
        raise NeedsInputError(
            "الوقت مع صباحًا/مساءً يجب أن يستخدم ساعة بين 1 و12."
        )
    if period in {"مساء", "مساءً", "م", "pm"} and hour < 12:
        hour += 12
    if period in {"صباحا", "صباحًا", "صباح", "ص", "am"} and hour == 12:
        hour = 0
    return hour, minute


def _time_candidates(text: str):
    normalized = text.translate(AR_DIGITS)
    rows = []
    occupied = []

    patterns = [
        re.compile(
            rf"(?:الساعه|الساعة|عند|at)\s*(\d{{1,2}})(?::(\d{{2}}))?\s*({_PERIODS})?",
            re.I,
        ),
        re.compile(rf"\b(\d{{1,2}}):(\d{{2}})\s*({_PERIODS})?", re.I),
        re.compile(rf"\b(\d{{1,2}})\s*({_PERIODS})\b", re.I),
    ]

    for index, pattern in enumerate(patterns):
        for match in pattern.finditer(normalized):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            if index < 2:
                hour = int(match.group(1))
                minute = int(match.group(2) or 0)
                period = match.group(3) or ""
            else:
                hour = int(match.group(1))
                minute = 0
                period = match.group(2) or ""
            hour, minute = _normalize_clock(hour, minute, period)
            rows.append({"text": match.group(0).strip(), "hour": hour, "minute": minute, "span": span})
            occupied.append(span)
    rows.sort(key=lambda row: row["span"][0])
    return rows


def _parse_time(text: str):
    candidates = _time_candidates(text)
    if not candidates:
        raise ValueError("حدد الوقت، مثال: الساعة 5:30 مساءً")

    unique = []
    for item in candidates:
        key = (item["hour"], item["minute"])
        if not any((row["hour"], row["minute"]) == key for row in unique):
            unique.append(item)
    if len(unique) > 1:
        refs = "، ".join(row["text"] for row in unique[:4])
        raise NeedsInputError(
            "وجدت أكثر من وقت محتمل (" + refs + "). "
            "إذا كنت تقصد نطاقًا، اكتب وقت البداية والمدة، مثال: الساعة 9 لمدة 60 دقيقة."
        )
    return unique[0]["hour"], unique[0]["minute"]


def _parse_reminder_minutes(text: str, default=60):
    normalized = text.translate(AR_DIGITS)
    if re.search(r"قبل\s+ساعتين", normalized):
        return 120
    if re.search(r"قبل\s+نصف\s+ساعه|قبل\s+نصف\s+ساعة", normalized):
        return 30
    match = re.search(r"قبل\s+(\d+)\s*(دقيقه|دقيقة|دقائق|minute)", normalized, re.I)
    if match:
        return max(0, min(40320, int(match.group(1))))
    match = re.search(r"قبل\s+(\d+)\s*(ساعه|ساعة|ساعات|hour)", normalized, re.I)
    if match:
        return max(0, min(40320, int(match.group(1)) * 60))
    return default


def parse_event_request(text: str, base: dt.datetime | None = None):
    base = base or now_local()
    event_date = _parse_date(text, base)
    hour, minute = _parse_time(text)
    start = dt.datetime.combine(event_date, dt.time(hour, minute), TZ)
    duration = 60
    normalized = text.translate(AR_DIGITS)
    dur = re.search(r"(?:لمده|لمدة|مدة)\s*(\d+)\s*(دقيقه|دقيقة|ساعه|ساعة)", normalized)
    if dur:
        duration = int(dur.group(1)) * (60 if "ساع" in dur.group(2) else 1)
    reminder = _parse_reminder_minutes(text)
    title = re.sub(r"^\s*(/remind|/calendar_add|ذكرني|ذكّرني|اضف|أضف|موعد)\s*", "", text, flags=re.I)
    title = re.sub(r"(اليوم|غد[ًاا]?|بكره|بكرة|بعد\s+غد|بعد\s+بكره)", "", title)
    title = re.sub(r"(?:يوم\s+)?(" + "|".join(map(re.escape, AR_DAYS)) + r")", "", title)
    title = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", "", title)
    title = re.sub(r"(?:الساعه|الساعة|عند|at)?\s*\d{1,2}(?::\d{2})?\s*(?:صباحا|صباحًا|صباح|ص|am|مساء|مساءً|م|pm)", "", title, flags=re.I)
    title = re.sub(r"قبل\s+(?:\d+\s*)?(?:دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات|ساعتين)", "", title)
    title = re.sub(r"قبل\s+نصف\s+(?:ساعه|ساعة)", "", title)
    title = re.sub(r"(?:لمده|لمدة|مدة)\s*\d+\s*(?:دقيقه|دقيقة|ساعه|ساعة)", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -،,")
    if not title:
        title = "تذكير"
    return {
        "title": title,
        "start": start,
        "end": start + dt.timedelta(minutes=duration),
        "reminder_minutes": reminder,
        "timezone": TZ_NAME,
    }


def calendar_auth_status() -> dict:
    raw_calendar = os.environ.get("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON", "").strip()
    raw_general = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    raw = raw_calendar or raw_general
    info = google_credentials.service_account_info(raw) if raw else None
    return {
        "service_account_present": bool(raw),
        "service_account_valid": bool(info),
        "calendar_id_mode": "primary" if CALENDAR_ID == "primary" else "custom",
        "path": "service-account" if info and CALENDAR_ID != "primary" else "oauth",
    }


def _calendar_service():
    raw_calendar = os.environ.get("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON", "").strip()
    raw_general = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    raw = raw_calendar or raw_general
    info = google_credentials.service_account_info(raw) if raw else None

    if raw and not info and CALENDAR_ID != "primary":
        raise RuntimeError("Google service-account credential is present but invalid")

    if info and CALENDAR_ID != "primary":
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    from connectors.google_workspace import services
    return services()[1]


def list_events(days_forward=7, max_results=30):
    cal = _calendar_service()
    start = now_local()
    end = start + dt.timedelta(days=days_forward)
    rows = cal.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=max_results,
    ).execute().get("items", [])
    return [
        {
            "id": row["id"],
            "title": row.get("summary", "(بدون عنوان)"),
            "start": row.get("start", {}).get("dateTime") or row.get("start", {}).get("date"),
            "end": row.get("end", {}).get("dateTime") or row.get("end", {}).get("date"),
            "link": row.get("htmlLink", ""),
            "reminder_minutes": int(row.get("extendedProperties", {}).get("private", {}).get("telegramReminderMinutes", "60")),
        }
        for row in rows
        if row.get("status") != "cancelled"
    ]


def create_event(proposal: dict):
    cal = _calendar_service()
    minutes = int(proposal.get("reminder_minutes", 60))
    body = {
        "summary": proposal["title"],
        "start": {"dateTime": proposal["start"].isoformat(), "timeZone": TZ_NAME},
        "end": {"dateTime": proposal["end"].isoformat(), "timeZone": TZ_NAME},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]},
        "extendedProperties": {"private": {"createdBy": "AbdulrahmanAIBot", "telegramReminderMinutes": str(minutes)}},
    }
    row = cal.events().insert(calendarId=CALENDAR_ID, body=body, sendUpdates="none").execute()
    return {"id": row["id"], "title": row.get("summary"), "start": row["start"].get("dateTime"), "link": row.get("htmlLink", "")}


def delete_event(event_id: str):
    _calendar_service().events().delete(calendarId=CALENDAR_ID, eventId=event_id, sendUpdates="none").execute()
    return {"id": event_id, "deleted": True}


def due_telegram_alerts(window_seconds=150):
    now = now_local()
    due = []
    for event in list_events(days_forward=2, max_results=50):
        start_raw = event.get("start", "")
        if "T" not in start_raw:
            continue
        start = dt.datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(TZ)
        alert_at = start - dt.timedelta(minutes=event["reminder_minutes"])
        delta = (now - alert_at).total_seconds()
        if 0 <= delta <= window_seconds:
            due.append(event)
    return due


def claim_alert(event_id: str, reminder_minutes: int):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{event_id}:{reminder_minutes}"
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if key in data:
        return False
    data[key] = now_local().isoformat()
    cutoff = now_local() - dt.timedelta(days=60)
    data = {k: v for k, v in data.items() if dt.datetime.fromisoformat(v) >= cutoff}
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, LEDGER)
    return True


# ---------------------------------------------------------------------------
# Rescheduling (إعادة الجدولة) — the agent DOES have Calendar access, so a
# reschedule request must route to a deterministic preview -> approval ->
# delete-old + create-new flow instead of falling through to a model that may
# wrongly claim it cannot reach the calendar.
# ---------------------------------------------------------------------------

# Canonical reschedule verbs (Arabic + English). Short verbs such as "أجل" are
# only recognized when followed by an event noun, so "أجل، سأرسلها" (a plain
# "yes") is never mistaken for a reschedule.
RESCHEDULE_VERBS = (
    r"إعادة\s*جدولة|اعادة\s*جدولة|أعدّ?\s*جدولة|"
    r"أجّل\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة|موعده)|"
    r"أجل\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة|موعده)|"
    r"أخّر\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"أخر\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"قدّم\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"قدم\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"أرجئ\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"أرّجئ\s+(?:ال)?(?:موعد|اجتماع|مقابلة|لقاء|جلسة|ورشة|مكالمة)|"
    r"غيّر\s*(?:ال)?موعد|غير\s*(?:ال)?موعد|"
    r"عدّ?ل\s*(?:ال)?موعد|"
    r"بدّ?ل\s*(?:ال)?موعد|"
    r"انقل\s*(?:ال)?موعد|نقل\s*(?:ال)?موعد|"
    r"reschedule|postpone|"
    r"move\s+(?:the\s+)?(?:meeting|appointment|event|call)\b|"
    r"change\s+(?:the\s+)?(?:meeting|appointment|event|call)\b|"
    r"delay\s+(?:the\s+)?(?:meeting|appointment|event|call)\b|"
    r"bring\s*forward"
)

_RESCHEDULE_VERB_RE = re.compile(
    r"^\s*(?:/reschedule\s+|/calendar_reschedule\s+)?" + r"(?:" + RESCHEDULE_VERBS + r")\s*[:،,\s]*",
    re.I,
)

_RESCHEDULE_CONNECTOR_RE = re.compile(
    r"\b(?:إلى|الى|إلى\s*يوم|الى\s*يوم|ليوم|لـ|to|on|for|until|till)\b",
    re.I,
)


def is_reschedule_action(text: str) -> bool:
    value = str(text or "").strip()
    if not value or value.startswith("/"):
        return False
    return bool(_RESCHEDULE_VERB_RE.search(value))


def _optional_duration_minutes(normalized: str) -> int | None:
    match = re.search(r"(?:لمده|لمدة|مدة)\s*(\d+)\s*(دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات)", normalized)
    if not match:
        return None
    return int(match.group(1)) * (60 if "ساع" in match.group(2) else 1)


def _optional_reminder_minutes(normalized: str) -> int | None:
    if re.search(r"قبل\s+ساعتين", normalized):
        return 120
    if re.search(r"قبل\s+نصف\s+(?:ساعه|ساعة)", normalized):
        return 30
    match = re.search(r"قبل\s+(\d+)\s*(دقيقه|دقيقة|دقائق|minute)", normalized, re.I)
    if match:
        return max(0, min(40320, int(match.group(1))))
    match = re.search(r"قبل\s+(\d+)\s*(ساعه|ساعة|ساعات|hour)", normalized, re.I)
    if match:
        return max(0, min(40320, int(match.group(1)) * 60))
    return None


_DIACRITICS_RE = re.compile(r"[\u064B-\u0652\u0640]")


def _reschedule_search(text: str) -> str:
    """Extract the event reference (title fragment) from a reschedule request."""
    value = _RESCHEDULE_VERB_RE.sub(" ", str(text or ""), count=1)
    value = re.sub(r"^/reschedule\s*", "", value, flags=re.I)
    value = _RESCHEDULE_CONNECTOR_RE.sub(" ", value)
    value = _DIACRITICS_RE.sub("", value)
    value = re.sub(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", " ", value)
    value = re.sub(r"(?:بعد\s+(?:غد|بكره)|غد[ًاا]?|بكره|بكرة|اليوم|tomorrow|today)", " ", value, flags=re.I)
    value = re.sub(r"(?:يوم\s+)?(" + "|".join(map(re.escape, AR_DAYS)) + r")", " ", value)
    value = re.sub(
        r"(?:الساعه|الساعة|عند|at)?\s*\d{1,2}(?::\d{2})?\s*(?:صباحا|صباحًا|صباح|ص|am|مساء|مساءً|م|pm)",
        " ", value, flags=re.I,
    )
    value = re.sub(r"(?:لمده|لمدة|مدة)\s*\d+\s*(?:دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات)", " ", value)
    value = re.sub(r"قبل\s+(?:\d+\s*)?(?:دقيقه|دقيقة|دقائق|ساعه|ساعة|ساعات|ساعتين|minute|minutes|hour|hours)", " ", value, flags=re.I)
    value = re.sub(r"قبل\s+نصف\s+(?:ساعه|ساعة)", " ", value)
    return re.sub(r"\s+", " ", value).strip(" -،,.")


def parse_reschedule_request(text: str, base: dt.datetime | None = None) -> dict:
    """Parse a reschedule request into an event reference + optional new fields.

    Returns ``{"search", "date", "time", "duration_minutes", "reminder_minutes"}``
    where every field except ``search`` may be ``None`` (meaning "inherit from the
    original event"). Ambiguous dates/times raise :class:`NeedsInputError`.
    """
    base = base or now_local()
    body = _RESCHEDULE_VERB_RE.sub(" ", str(text or ""), count=1)
    body = re.sub(r"^/reschedule\s*", "", body, flags=re.I)
    body = _RESCHEDULE_CONNECTOR_RE.sub(" ", body)
    normalized = body.translate(AR_DIGITS)

    new_date = None
    try:
        new_date = _parse_date(normalized, base)
    except ValueError:
        new_date = None

    new_time = None
    try:
        new_time = _parse_time(normalized)
    except ValueError:
        new_time = None

    return {
        "search": _reschedule_search(text),
        "date": new_date,
        "time": new_time,
        "duration_minutes": _optional_duration_minutes(normalized),
        "reminder_minutes": _optional_reminder_minutes(normalized),
    }


def find_events(query: str, days_forward: int = 30, max_results: int = 100) -> list:
    """Return upcoming events whose title contains ``query`` (case-insensitive)."""
    term = (query or "").strip()
    if not term:
        return []
    matches = []
    for event in list_events(days_forward=days_forward, max_results=max_results):
        if term.lower() in event.get("title", "").lower():
            matches.append(event)
    return matches


def reschedule_event(old_event_id: str, proposal: dict) -> dict:
    """Reschedule an existing event: verify it, create the new one, delete the old.

    Fails closed — if the original event can no longer be found, nothing is
    created or deleted, so a stale approval cannot mutate an unrelated event.
    """
    cal = _calendar_service()
    try:
        cal.events().get(calendarId=CALENDAR_ID, eventId=old_event_id).execute()
    except Exception as exc:  # noqa: BLE001 - translate any lookup failure to a safe stop
        raise RuntimeError(
            "تعذر إيجاد الموعد الأصلي لإعادة الجدولة (ربما حُذف أو غُيّر يدويًا). "
            "لم يُنفَّذ أي تغيير."
        ) from exc
    created = create_event(proposal)
    deleted = delete_event(old_event_id)
    return {
        "id": created["id"],
        "title": created["title"],
        "start": created["start"],
        "link": created.get("link", ""),
        "old_id": deleted["id"],
    }

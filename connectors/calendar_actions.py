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
        return dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    dmy = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if dmy:
        return dt.date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
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
        try:
            date_value = _date_value(token, base)
        except ValueError:
            continue
        rows.append({"text": token.strip(), "date": date_value, "span": match.span()})
    return rows


def _parse_date(text: str, base: dt.datetime) -> dt.date:
    candidates = _date_candidates(text, base)
    if not candidates:
        raise ValueError("حدد التاريخ: اليوم، غدًا، اسم اليوم، أو YYYY-MM-DD")

    unique = []
    for item in candidates:
        if not any(row["date"] == item["date"] for row in unique):
            unique.append(item)
    if len(unique) > 1:
        refs = "، ".join(row["text"] for row in unique[:4])
        raise ValueError(
            "NEEDS_INPUT: وجدت أكثر من تاريخ محتمل (" + refs + "). "
            "اكتب موعدًا واحدًا فقط مع تاريخه ووقته."
        )
    return unique[0]["date"]


def _normalize_clock(hour: int, minute: int, period: str):
    period = (period or "").lower()
    if minute > 59 or hour > 23:
        raise ValueError("الوقت غير صالح")
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
        raise ValueError(
            "NEEDS_INPUT: وجدت أكثر من وقت محتمل (" + refs + "). "
            "اكتب موعدًا واحدًا فقط مع تاريخه ووقته."
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

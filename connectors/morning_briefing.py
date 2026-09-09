# -*- coding: utf-8 -*-
"""Morning Briefing Mode (وضع التوجيه الصباحي) — interactive Telegram dashboard.

Review findings this module addresses (Google Sheets retrieval for overdue
tasks and clinics):
1. brief_discovery.discover() flags overdue rows by the keyword «متأخر» only,
   and _dated_items() looks exclusively at FUTURE dates. Rows whose deadline
   already passed without the keyword were invisible to every brief.
   -> overdue_tasks() adds column-aware, date-based overdue detection
      (الموعد النهائي / الاستحقاق / Deadline columns) with a keyword fallback.
2. No connector read the «تقارير المشرفين» tab, although its schema is fixed
   by rehab_supervisor_form.gs (الجاهزية، المشرف، القسم / العيادة، التعثرات).
   -> clinic_readiness() extracts the LATEST readiness per clinic by header
      name (column-order safe) and sorts by severity (🔴 → 🟡 → 🟢).
3. Clinic appointments lived only inside generic Calendar listings.
   -> today_clinic_events() reads today's Google Calendar events and marks
      clinic-related ones.

Telegram layer:
- /morning (or the natural phrases «التوجيه الصباحي» / «صباح الخير») renders
  the dashboard with three inline buttons:
    [ 🎙️ إفراغ ذهني سريع ]  [ 📢 إرسال توجيه المشرفين ]  [ 📊 فتح شيت المهام ]
- handle_callback_query() answers every callback, enforces the same chat
  authorization as messages, and dispatches to the button actions.
- Brain dump: a 10-minute capture session; each text/voice message is stored
  in «مدخلات الوكيل» (category BRAIN_DUMP) with a save receipt. «تم» closes it.
- Supervisor brief: deterministic draft built from live data, then explicit
  approval via /confirm_supervisor_brief. The bot never messages unauthorized
  chats; the owner forwards the approved text (documented in the reply).
- Open tasks sheet: direct link with gid resolution + compact overdue list.

Reads are fail-soft: one failing source is reported without blocking the rest.
External writes stay behind explicit approval, matching repo policy.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import time

from connectors import sheet_intelligence as sheets

TASKS_TAB = os.environ.get("MORNING_TASKS_SHEET", "خطة الإنجاز والمهام").strip()
TASKS_TABS = (TASKS_TAB, "Projects")
SUPERVISOR_REPORTS_TAB = os.environ.get("MORNING_SUPERVISOR_SHEET", "تقارير المشرفين").strip()
BRAIN_DUMP_WINDOW_SECONDS = 600
SUPERVISOR_BRIEF_WINDOW_SECONDS = 900

CB_BRAIN_DUMP = "morning:brain_dump"
CB_SUPERVISOR_BRIEF = "morning:supervisor_brief"
CB_OPEN_TASKS = "morning:open_tasks"

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DATE_RX = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_DONE_RE = re.compile(
    r"منجز|مكتمل|مغلق|تم\s+الإنجاز|تم\s+انجاز|done|completed|closed", re.I
)
_OVERDUE_RE = re.compile(r"متأخر|متأخرة|تجاوز\s+الموعد|تأخر\s+الإنجاز|overdue|past\s+due", re.I)
_DEADLINE_KEYS = (
    "الموعد النهائي", "الموعد النهائى", "الاستحقاق", "تاريخ التسليم",
    "تاريخ الاستحقاق", "الموعد", "deadline", "due",
)
_STATUS_KEYS = ("الحالة", "الحاله", "status")
_SUPERVISOR_KEYS = ("المشرف", "supervisor")
_CLINIC_KEYS = ("القسم / العيادة", "العيادة", "القسم", "clinic")
_READINESS_KEYS = ("الجاهزية", "جاهزية", "readiness")
_BLOCKER_KEYS = ("التعثرات", "التعثر", "blockers")
_CLINIC_RE = re.compile(r"عيادة|قسم\s+التأهيل|تأهيل|علاج\s+طبيعي|clinic|rehab", re.I)
_MORNING_TRIGGER_RE = re.compile(
    r"^\s*(?:التوجيه\s+الصباحي|وضع\s+التوجيه\s+الصباحي|الوضع\s+الصباحي|وضع\s+الصباح|"
    r"لوحة\s+الصباح|صباح\s+الخير|morning\s+(?:brief|mode))"
    r"(?=\s|$|[.!،,؟?])",
    re.I,
)
_BRAIN_DUMP_END_WORDS = {"تم", "خلاص", "انتهيت", "إنهاء", "إلغاء", "الغاء", "cancel", "done"}

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)")
_MRN_RE = re.compile(r"(?i)(mrn|medical record|رقم الملف|رقم الهوية)\s*[:#-]?\s*[A-Z0-9-]+")

bot = None  # bound by install(); the live telegram bot module.

_PENDING_BRAIN_DUMPS: dict[str, dict] = {}
_PENDING_SUPERVISOR_BRIEFS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_error(exc: Exception) -> str:
    try:
        from connectors.model_gateway import _safe_error as model_safe_error

        return model_safe_error(exc)
    except Exception:
        return str(exc).replace("\n", " ")[:240]


def _today() -> dt.date:
    try:
        from connectors.calendar_actions import now_local

        return now_local().date()
    except Exception:
        return dt.date.today()


def _now_text() -> str:
    now_fn = getattr(bot, "_now", None)
    if callable(now_fn):
        try:
            return str(now_fn())
        except Exception:
            pass
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")


def _redact_text(text: str) -> str:
    value = str(text or "")
    redactor = getattr(bot, "_redact", None)
    if callable(redactor):
        try:
            return str(redactor(value))
        except Exception:
            pass
    value = _EMAIL_RE.sub("[EMAIL_REDACTED]", value)
    value = _PHONE_RE.sub("[PHONE_REDACTED]", value)
    return _MRN_RE.sub(r"\1: [IDENTIFIER_REDACTED]", value)


def _language_of(text: str) -> str:
    lang_fn = getattr(bot, "_language", None)
    if callable(lang_fn):
        try:
            return lang_fn(text)
        except Exception:
            pass
    return "ar" if re.search(r"[\u0600-\u06FF]", text or "") else "en"


def _typing(chat_id: int):
    try:
        bot.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


def _sheets_snapshot() -> dict:
    return sheets.snapshot(max_rows=120, max_cols=16)


def _find_column(headers: list[str], keys: tuple[str, ...]) -> int | None:
    for index, header in enumerate(headers):
        cleaned = re.sub(r"\s+", " ", str(header or "").strip()).lower()
        if not cleaned:
            continue
        for key in keys:
            if cleaned == key.lower() or key.lower() in cleaned:
                return index
    return None


def _parse_dates(value: str) -> list[dt.date]:
    found = []
    for y, m, d in _DATE_RX.findall(str(value or "").translate(_AR_DIGITS)):
        try:
            found.append(dt.date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return found


def _item_summary(item: dict, width: int = 150) -> str:
    values = [str(x).strip() for x in (item.get("values") or []) if str(x).strip()]
    preview = " | ".join(values[:5])[:width] or "بدون وصف"
    reason = f" ({item['reason']})" if item.get("reason") else ""
    return (
        f"{item.get('sheet', '—')} — صف {item.get('row', '—')}{reason}: "
        + _redact_text(preview)
    )


# ---------------------------------------------------------------------------
# 1) Data layer — Google Sheets / Calendar reads (reviewed logic)
# ---------------------------------------------------------------------------

def overdue_tasks(data: dict, today: dt.date | None = None, limit: int = 8) -> list[dict]:
    """Return overdue task rows with provenance (sheet + row) and a reason.

    Detection is column-aware: when the tab has a deadline column
    (الموعد النهائي / الاستحقاق / Deadline), only that column's dates are
    evaluated, so old «آخر تحديث» dates can never create false positives.
    Rows marked done (منجز/مكتمل/مغلق) are skipped. Rows without a parsable
    deadline fall back to the explicit «متأخر/overdue» keyword.
    """
    today = today or _today()
    results: list[dict] = []
    for tab in TASKS_TABS:
        rows = data.get(tab) if isinstance(data, dict) else None
        if not rows or len(rows) < 2:
            continue
        headers = [str(x or "").strip() for x in rows[0]]
        deadline_col = _find_column(headers, _DEADLINE_KEYS)
        status_col = _find_column(headers, _STATUS_KEYS)

        def cell(values: list[str], index: int | None) -> str:
            return values[index] if index is not None and index < len(values) else ""

        for row_no, row in enumerate(rows[1:], start=2):
            values = [str(x or "").strip() for x in row]
            if not any(values):
                continue
            status_text = cell(values, status_col)
            if _DONE_RE.search(status_text or " | ".join(values)):
                continue
            reason = ""
            if deadline_col is not None:
                dates = _parse_dates(cell(values, deadline_col))
                if dates and max(dates) < today:
                    reason = f"تجاوز الموعد ({max(dates).isoformat()})"
            if not reason and _OVERDUE_RE.search(" | ".join(values)):
                reason = "موسومة كمتأخرة"
            if reason:
                results.append({
                    "sheet": tab,
                    "row": row_no,
                    "values": values,
                    "reason": reason,
                    "deadline": cell(values, deadline_col),
                })
                if len(results) >= limit:
                    return results
    return results


def _readiness_severity(readiness: str) -> int:
    value = str(readiness or "")
    if "🔴" in value or "غير جاهز" in value:
        return 0
    if "🟡" in value or "جزئي" in value:
        return 1
    if "🟢" in value or "جاهز بالكامل" in value:
        return 2
    return 3


def clinic_readiness(data: dict, limit: int = 6) -> list[dict]:
    """Latest readiness per clinic from the supervisor reports tab.

    Column-order safe: every field is located by header name using the fixed
    schema of rehab_supervisor_form.gs. Later rows win (latest report per
    clinic). Sorted 🔴 → 🟡 → 🟢 → unknown.
    """
    rows = data.get(SUPERVISOR_REPORTS_TAB) if isinstance(data, dict) else None
    if not rows or len(rows) < 2:
        return []
    headers = [str(x or "").strip() for x in rows[0]]
    clinic_col = _find_column(headers, _CLINIC_KEYS)
    if clinic_col is None:
        return []
    readiness_col = _find_column(headers, _READINESS_KEYS)
    supervisor_col = _find_column(headers, _SUPERVISOR_KEYS)
    blocker_col = _find_column(headers, _BLOCKER_KEYS)

    def cell(values: list[str], index: int | None) -> str:
        return values[index] if index is not None and index < len(values) else ""

    latest: dict[str, dict] = {}
    order: list[str] = []
    for row_no, row in enumerate(rows[1:], start=2):
        values = [str(x or "").strip() for x in row]
        clinic = cell(values, clinic_col)
        if not clinic:
            continue
        if clinic not in latest:
            order.append(clinic)
        latest[clinic] = {
            "clinic": clinic,
            "readiness": cell(values, readiness_col),
            "supervisor": cell(values, supervisor_col),
            "note": cell(values, blocker_col)[:120],
            "row": row_no,
            "sheet": SUPERVISOR_REPORTS_TAB,
        }
    ranked = sorted(
        latest.values(),
        key=lambda item: (_readiness_severity(item.get("readiness")), order.index(item["clinic"])),
    )
    return ranked[:limit]


def today_clinic_events(limit: int = 8) -> tuple[list[dict], str | None]:
    """Today's Calendar events, flagging clinic-related titles.

    Calendar is fail-soft: a Calendar failure is returned as an error string
    and must not block the Sheets-based dashboard.
    """
    try:
        from connectors.calendar_actions import list_events, now_local
    except Exception as exc:  # noqa: BLE001 - optional dependency boundary
        return [], "Google Calendar (استيراد): " + _safe_error(exc)
    try:
        today = now_local().date().isoformat()
        events = []
        for event in list_events(days_forward=1, max_results=30):
            start = str(event.get("start") or "")
            if start[:10] != today:
                continue
            item = dict(event)
            item["is_clinic"] = bool(_CLINIC_RE.search(str(event.get("title") or "")))
            events.append(item)
        events.sort(key=lambda item: str(item.get("start") or ""))
        return events[:limit], None
    except Exception as exc:  # noqa: BLE001 - external Calendar boundary
        return [], "Google Calendar: " + _safe_error(exc)


def morning_payload(tasks_limit: int = 8, clinics_limit: int = 6, events_limit: int = 8) -> dict:
    """Collect all morning dashboard sources; each source fails independently."""
    errors: list[str] = []
    data: dict = {}
    try:
        data = _sheets_snapshot()
        if not data:
            errors.append("الشيتات: لا توجد بيانات مقروءة")
    except Exception as exc:  # noqa: BLE001 - external Sheets boundary
        errors.append("Google Sheets: " + _safe_error(exc))
    overdue = overdue_tasks(data, limit=tasks_limit) if data else []
    clinics = clinic_readiness(data, limit=clinics_limit) if data else []
    events, calendar_error = today_clinic_events(limit=events_limit)
    if calendar_error:
        errors.append(calendar_error)
    return {
        "overdue": overdue,
        "clinics": clinics,
        "today_events": events,
        "errors": errors,
        "generated_at": _now_text(),
    }


def tasks_sheet_link() -> str:
    """Direct edit link to the tasks tab; falls back to the workbook URL."""
    sheet_id = (sheets.SHEET_ID or "").strip()
    if not sheet_id and bot is not None:
        sheet_id = str(getattr(bot, "GOOGLE_SHEET_ID", "") or "").strip()
    if not sheet_id:
        return "⚠️ GOOGLE_SHEET_ID غير مضبوط؛ لا أستطيع توليد رابط الشيت."
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    try:
        for row in sheets.metadata():
            if str(row.get("title", "")) == TASKS_TAB and row.get("sheetId") is not None:
                return f"{base}/edit#gid={row['sheetId']}"
    except Exception as exc:  # noqa: BLE001 - external Sheets boundary
        print(f"Tasks sheet link warning: {_safe_error(exc)}", flush=True)
    return base + "/edit"


# ---------------------------------------------------------------------------
# 2) Rendering — dashboard, supervisor brief, keyboard
# ---------------------------------------------------------------------------

def morning_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🎙️ إفراغ ذهني سريع", "callback_data": CB_BRAIN_DUMP}],
            [{"text": "📢 إرسال توجيه المشرفين", "callback_data": CB_SUPERVISOR_BRIEF}],
            [{"text": "📊 فتح شيت المهام", "callback_data": CB_OPEN_TASKS}],
        ]
    }


def render_morning_dashboard(payload: dict) -> str:
    overdue = payload.get("overdue") or []
    clinics = payload.get("clinics") or []
    events = payload.get("today_events") or []
    errors = payload.get("errors") or []
    stamp = str(payload.get("generated_at") or "")[:16].replace("T", " ")

    lines = ["🌤️ وضع التوجيه الصباحي", f"⏱️ {stamp} (توقيت الرياض)", "", f"⏰ مهام متأخرة: {len(overdue)}"]
    if overdue:
        lines.extend("• " + _item_summary(item) for item in overdue[:5])
    else:
        lines.append("• لا توجد مهام متأخرة مؤكدة.")

    lines += ["", f"🏥 جاهزية العيادات (آخر تقارير المشرفين): {len(clinics)}"]
    if clinics:
        for clinic in clinics:
            note = f" — {clinic['note']}" if clinic.get("note") else ""
            lines.append(f"• {clinic['clinic']}: {clinic.get('readiness') or 'غير محددة'}{note}")
    else:
        lines.append("• لا توجد تقارير مشرفين مؤكدة.")

    clinic_events = [event for event in events if event.get("is_clinic")]
    lines += ["", f"📅 مواعيد اليوم: {len(events)}" + (f" (منها {len(clinic_events)} للعيادات)" if events else "")]
    if events:
        for event in events[:5]:
            time_part = str(event.get("start") or "")[11:16]
            flag = " 🏥" if event.get("is_clinic") else ""
            lines.append(f"• {time_part or '—'} — {_redact_text(str(event.get('title') or '(بدون عنوان)'))[:80]}{flag}")
    else:
        lines.append("• لا توجد مواعيد مؤكدة لبقية اليوم.")

    if errors:
        lines += ["", "⚠️ مصادر متعذرة (استُكملت البقية): " + "؛ ".join(str(x)[:120] for x in errors[:2])]
    lines += ["", "اختر من الأزرار بالأسفل 👇"]
    return "\n".join(lines)[:3500]


def build_supervisor_brief(payload: dict) -> str:
    """Deterministic supervisors briefing draft built only from live evidence."""
    generated = str(payload.get("generated_at") or "")
    date_text = generated[:10] or str(_today())
    overdue = payload.get("overdue") or []
    clinics = payload.get("clinics") or []
    errors = payload.get("errors") or []

    lines = [f"📢 توجيه المشرفين — {date_text}", "قسم التأهيل", ""]

    lines.append("1) جاهزية العيادات (آخر تقارير المشرفين):")
    if clinics:
        for clinic in clinics[:6]:
            lines.append(f"• {clinic['clinic']}: {clinic.get('readiness') or 'غير محددة'}")
    else:
        lines.append("• لا توجد تقارير جاهزية حديثة مؤكدة.")

    lines += ["", f"2) مهام متأخرة تحتاج متابعة اليوم ({len(overdue)}):"]
    if overdue:
        lines.extend("• " + _item_summary(item) for item in overdue[:5])
    else:
        lines.append("• لا توجد مهام متأخرة مؤكدة.")

    lines += ["", "3) توجيهات اليوم:"]
    red = [c for c in clinics if _readiness_severity(c.get("readiness")) == 0]
    yellow = [c for c in clinics if _readiness_severity(c.get("readiness")) == 1]
    if red:
        lines.append("• معالجة عوائق الجاهزية في: " + "، ".join(c["clinic"] for c in red) + "، ورفع تحديث الحالة قبل نهاية الدوام.")
    if yellow:
        lines.append("• إغلاق ملاحظات الجاهزية الجزئية في: " + "، ".join(c["clinic"] for c in yellow) + ".")
    if overdue:
        lines.append("• تحديث حالة المهام المتأخرة المذكورة أعلاه في شيت المهام اليوم مع ذكر السبب.")
    lines.append("• رفع أي بلاغ طارئ فورًا عبر نموذج البلاغ الطارئ (بدون أي بيانات مرضى).")

    if errors:
        lines += ["", "⚠️ بُني التوجيه على المصادر المتاحة فقط؛ مصادر متعذرة: " + "؛ ".join(str(x)[:120] for x in errors[:2])]
    return "\n".join(lines)[:3500]


# ---------------------------------------------------------------------------
# 3) Telegram layer — keyboard sending, callbacks, commands
# ---------------------------------------------------------------------------

def send_with_keyboard(chat_id: int, text: str, keyboard: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "text": str(text or "")[:3800],
        "reply_markup": json.dumps(keyboard or morning_keyboard(), ensure_ascii=False),
    }
    bot.api("sendMessage", payload)


def _answer_callback_factory(callback_query_id: str):
    """answerCallbackQuery may be sent exactly once per query; guard it."""
    state = {"answered": False}

    def answer(text: str = "", show_alert: bool = False) -> None:
        if state["answered"] or not callback_query_id:
            return
        state["answered"] = True
        payload = {"callback_query_id": callback_query_id, "text": str(text)[:190]}
        if show_alert:
            payload["show_alert"] = True
        try:
            bot.api("answerCallbackQuery", payload)
        except Exception as exc:  # noqa: BLE001 - Telegram boundary
            print(f"answerCallbackQuery warning: {_safe_error(exc)}", flush=True)

    return answer


def _cb_brain_dump(chat_id: int):
    _PENDING_BRAIN_DUMPS[str(chat_id)] = {
        "expires": time.time() + BRAIN_DUMP_WINDOW_SECONDS,
        "count": 0,
        "captures": [],
    }
    bot.send(
        chat_id,
        "🎙️ وضع الإفراغ الذهني مفتوح الآن (10 دقائق).\n"
        "أرسل أفكارك ومهامك رسالة رسالة — نصًا أو صوتًا — وسألتقطها في «مدخلات الوكيل».\n"
        "عند الانتهاء أرسل: تم",
    )


def _cb_supervisor_brief(chat_id: int):
    _typing(chat_id)
    payload = morning_payload()
    draft = build_supervisor_brief(payload)
    token = secrets.token_hex(3)
    _PENDING_SUPERVISOR_BRIEFS[token] = {
        "chat_id": str(chat_id),
        "draft": draft,
        "expires": time.time() + SUPERVISOR_BRIEF_WINDOW_SECONDS,
    }
    bot.send(
        chat_id,
        "📢 مسودة توجيه المشرفين — لم تُرسل بعد\n\n"
        + draft
        + "\n\nللاعتماد خلال 15 دقيقة:\n/confirm_supervisor_brief "
        + token
        + "\nبعد الاعتماد يظهر النص النهائي لتحويله إلى مجموعة المشرفين بنفسك "
        "(البوت لا يراسل محادثات غير مصرح لها).",
    )


def _cb_open_tasks(chat_id: int):
    _typing(chat_id)
    lines = ["📊 شيت المهام", tasks_sheet_link(), ""]
    try:
        overdue = overdue_tasks(_sheets_snapshot())
        lines.append(f"⏰ المهام المتأخرة الآن: {len(overdue)}")
        if overdue:
            lines.extend("• " + _item_summary(item) for item in overdue[:5])
        else:
            lines.append("• لا توجد مهام متأخرة مؤكدة.")
    except Exception as exc:  # noqa: BLE001 - external Sheets boundary
        lines.append("⚠️ تعذر قراءة المهام المتأخرة الآن: " + _safe_error(exc))
    bot.send(chat_id, "\n".join(lines))


_CALLBACK_ACTIONS = {
    CB_BRAIN_DUMP: _cb_brain_dump,
    CB_SUPERVISOR_BRIEF: _cb_supervisor_brief,
    CB_OPEN_TASKS: _cb_open_tasks,
}


def handle_callback_query(callback_query: dict):
    """Central Callback Query Handler for the morning dashboard buttons.

    Guarantees: one answerCallbackQuery per query, the same chat authorization
    as normal messages (callback_data is client-supplied and untrusted), and
    no exception ever escapes to the webhook worker.
    """
    callback_query = callback_query or {}
    callback_query_id = str(callback_query.get("id") or "")
    if not callback_query_id:
        return
    answer = _answer_callback_factory(callback_query_id)
    try:
        if bot is None:
            answer("⚠️ وضع التوجيه الصباحي غير مهيأ.", show_alert=True)
            return
        chat = (callback_query.get("message") or {}).get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            answer()
            return
        if not bot._authorized(chat_id, chat.get("type", "")):
            answer("⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.", show_alert=True)
            return
        action = _CALLBACK_ACTIONS.get(str(callback_query.get("data") or ""))
        if action is None:
            answer("⚠️ زر غير معروف؛ افتح اللوحة من جديد عبر /morning.")
            return
        answer("⏳ جارٍ التنفيذ...")
        action(int(chat_id))
    except Exception as exc:  # noqa: BLE001 - Telegram action boundary
        safe = _safe_error(exc)
        print(f"Morning callback error [{callback_query.get('data')}]: {safe}", flush=True)
        answer("❌ تعذر التنفيذ: " + safe[:150], show_alert=True)
        try:
            chat_id = ((callback_query.get("message") or {}).get("chat") or {}).get("id")
            if chat_id is not None:
                bot.send(chat_id, "❌ تعذر تنفيذ طلب لوحة التوجيه الصباحي: " + safe[:200])
        except Exception:  # noqa: BLE001 - best-effort notification
            pass


def command_morning(chat_id: int):
    """Render the interactive morning dashboard with the three buttons."""
    _typing(chat_id)
    try:
        payload = morning_payload()
        send_with_keyboard(chat_id, render_morning_dashboard(payload))
    except Exception as exc:  # noqa: BLE001 - keep webhook mode non-raising
        safe = _safe_error(exc)
        print(f"Morning dashboard error: {safe}", flush=True)
        bot.send(chat_id, "❌ تعذر بناء لوحة التوجيه الصباحي: " + safe[:220])


def command_confirm_supervisor_brief(chat_id: int, token: str):
    token = (token or "").strip()
    item = _PENDING_SUPERVISOR_BRIEFS.get(token)
    if not item:
        bot.send(chat_id, "❌ رمز اعتماد توجيه المشرفين غير صالح.")
        return
    if item.get("expires", 0) < time.time():
        _PENDING_SUPERVISOR_BRIEFS.pop(token, None)
        bot.send(chat_id, "❌ انتهت مدة رمز اعتماد توجيه المشرفين (15 دقيقة). أنشئ مسودة جديدة من /morning.")
        return
    if item.get("chat_id") != str(chat_id):
        # Wrong chat: keep the token valid for the chat that created the draft.
        bot.send(chat_id, "❌ هذا الرمز لا يخص هذه المحادثة.")
        return
    _PENDING_SUPERVISOR_BRIEFS.pop(token, None)
    # bot._save_status is fire-and-forget (it never raises), so the receipt is
    # written through bot._append directly: a claimed save must have a real receipt.
    logged = False
    try:
        bot._append(bot.STATUS_TAB, [
            bot._now(), "MORNING_SUPERVISOR_BRIEF", "APPROVED",
            item["draft"][:1000], "v1.1", bot.AWS_REGION, bot.BEDROCK_MODEL_ID, bot._now(),
        ])
        logged = True
    except Exception as exc:  # noqa: BLE001 - Sheets boundary
        print(f"Supervisor brief status log error: {_safe_error(exc)}", flush=True)
    header = (
        f"✅ تم اعتماد توجيه المشرفين وتوثيقه في Google Sheets ({bot.STATUS_TAB}).\n"
        if logged else
        "⚠️ تم الاعتماد، لكن تعذر توثيقه في Google Sheets الآن.\n"
    )
    bot.send(
        chat_id,
        header
        + "انسخ النص التالي وأرسله إلى مجموعة المشرفين عبر قناتك المعتمدة:\n\n"
        + item["draft"],
    )


# ---------------------------------------------------------------------------
# 4) Brain dump capture
# ---------------------------------------------------------------------------

def _save_brain_dump_row(iid, message: dict, text: str, kind: str, attachment: str) -> bool:
    """Persist one brain dump row using the exact «مدخلات الوكيل» schema."""
    chat_id = str((message.get("chat") or {}).get("id", ""))
    row = [
        iid, _now_text(), "TELEGRAM", chat_id, kind,
        _redact_text(str(text)), _language_of(text), "BRAIN_DUMP", "NORMAL",
        "COMPLETED", "", _now_text(), "", str(attachment or "")[:200],
        "وضع التوجيه الصباحي — إفراغ ذهني",
    ]
    try:
        bot._append(bot.INTAKE_TAB, row)
        return True
    except Exception as exc:  # noqa: BLE001 - Sheets boundary
        print(f"Brain dump save error: {_safe_error(exc)}", flush=True)
        return False


def _capture_brain_dump(message: dict, session: dict):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text, kind, attachment = bot._message_payload(message)
    iid = bot._local_capture(text, message, kind)
    try:
        if kind in {"VOICE", "AUDIO"}:
            bot.send(chat_id, "🎙️ جارٍ تفريغ الصوت...")
            text = bot._transcribe_telegram(attachment, kind)
            bot.send(chat_id, "📝 التفريغ:\n" + str(text)[:1500])
        if not str(text or "").strip():
            bot.send(chat_id, "⚠️ الرسالة فارغة؛ لم يُلتقط شيء. أرسل نصًا أو صوتًا، أو أنهِ بكلمة «تم».")
            return
        saved = _save_brain_dump_row(iid, message, str(text), kind, attachment)
        session["count"] = int(session.get("count", 0)) + 1
        session.setdefault("captures", []).append(iid)
        remaining = max(0, int(session.get("expires", time.time()) - time.time()) // 60)
        privacy_note = ""
        if _redact_text(str(text)) != str(text):
            privacy_note = "\n🔒 طُبّق إخفاء الخصوصية على المحتوى الحساس قبل الحفظ."
        receipt = (
            f"💾 إيصال الحفظ: {bot.INTAKE_TAB} — {iid}"
            if saved else
            "⚠️ لم يصدر إيصال حفظ من Google Sheets؛ أعد إرسال الملاحظة لاحقًا."
        )
        bot.send(
            chat_id,
            f"✅ التُقطت ({session['count']}). متبقٍ حوالي {remaining} دقيقة. "
            f"أرسل التالية أو أنهِ بكلمة «تم».\n{receipt}{privacy_note}",
        )
    except Exception as exc:  # noqa: BLE001 - keep the session alive on failure
        safe = _safe_error(exc)
        bot.send(
            chat_id,
            "❌ تعذر التقاط هذه الرسالة: " + safe[:220]
            + "\nالجلسة ما زالت مفتوحة؛ أعد المحاولة أو أنهِ بكلمة «تم».",
        )
        bot._save_intake(iid, message, str(text), kind, attachment, "ERROR", error=safe)


# ---------------------------------------------------------------------------
# 5) Installation — wraps the live bot module (webhook + polling modes)
# ---------------------------------------------------------------------------

def _run_chat_command(chat: dict, message: dict, action, status: str = "COMPLETED"):
    """Authorized command execution with the standard intake audit trail."""
    chat_id = chat.get("id")
    if chat_id is None:
        return
    if not bot._authorized(chat_id, chat.get("type", "")):
        bot.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
        return
    text, kind, attachment = bot._message_payload(message)
    iid = bot._local_capture(text, message, kind)
    try:
        action(int(chat_id))
        bot._save_intake(iid, message, text, kind, attachment, status)
    except Exception as exc:  # noqa: BLE001 - command boundary
        safe = _safe_error(exc)
        bot.send(chat_id, "❌ تعذر تنفيذ طلب التوجيه الصباحي: " + safe[:220])
        bot._save_intake(iid, message, text, kind, attachment, "ERROR", error=safe)


def install(bot_module):
    """Attach Morning Briefing Mode to the live bot module.

    Idempotent (guarded by _morning_briefing_installed). Installs cleanly in
    webhook mode (called at the bottom of connectors/telegram_bot.py, wrapping
    the outermost handle_message) and in polling mode.
    """
    global bot
    bot = bot_module
    if getattr(bot_module, "_morning_briefing_installed", False):
        return bot_module

    original_handle = bot_module.handle_message
    original_configure = bot_module.configure_commands
    original_start = bot_module.command_start

    def handle_message(message: dict):
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        raw = (message.get("text") or message.get("caption") or "").strip()
        if chat_id is None:
            return original_handle(message)

        # Active brain-dump session captures everything except its end words.
        session = _PENDING_BRAIN_DUMPS.get(str(chat_id))
        if session is not None and session.get("expires", 0) < time.time():
            _PENDING_BRAIN_DUMPS.pop(str(chat_id), None)
            session = None
        if session is not None and bot._authorized(chat_id, chat.get("type", "")):
            if raw in _BRAIN_DUMP_END_WORDS:
                _PENDING_BRAIN_DUMPS.pop(str(chat_id), None)
                bot.send(
                    chat_id,
                    f"✅ أُغلقت جلسة الإفراغ الذهني. عدد ما التُقط: {session.get('count', 0)}.\n"
                    "افتح لوحة جديدة في أي وقت عبر /morning.",
                )
                return
            return _capture_brain_dump(message, session)

        command = raw.split()[0].split("@")[0].lower() if raw else ""
        if command == "/morning":
            return _run_chat_command(chat, message, command_morning)
        if command == "/confirm_supervisor_brief":
            token = raw[len(command):].strip()
            return _run_chat_command(
                chat, message, lambda cid: command_confirm_supervisor_brief(cid, token)
            )
        if _MORNING_TRIGGER_RE.match(raw):
            return _run_chat_command(chat, message, command_morning)
        return original_handle(message)

    def configure_commands():
        original_configure()
        try:
            commands = bot_module.api("getMyCommands") or []
            existing = {str(item.get("command", "")) for item in commands}
            if "morning" not in existing:
                commands.append({"command": "morning", "description": "لوحة التوجيه الصباحي التفاعلية"})
                bot_module.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:  # noqa: BLE001 - menu registration is cosmetic
            print(f"Morning command menu warning: {_safe_error(exc)}", flush=True)

    def command_start(chat_id: int):
        original_start(chat_id)
        bot_module.send(
            chat_id,
            "\n🌤️ وضع التوجيه الصباحي\n/morning — لوحة تفاعلية: إفراغ ذهني سريع، "
            "توجيه المشرفين، فتح شيت المهام",
        )

    bot_module.handle_message = handle_message
    bot_module.handle_callback_query = handle_callback_query
    bot_module.command_morning = command_morning
    bot_module.command_confirm_supervisor_brief = command_confirm_supervisor_brief
    bot_module.configure_commands = configure_commands
    bot_module.command_start = command_start
    bot_module._morning_briefing_installed = True
    return bot_module

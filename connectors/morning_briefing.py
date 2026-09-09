# -*- coding: utf-8 -*-
"""Morning Briefing Mode v2 (وضع التوجيه الصباحي) — proactive executive triage dashboard.

Spec compatibility audit (vs connectors/sheet_intelligence.py + task_delegation.py):
- get_sheet_intelligence() does NOT exist in sheet_intelligence.py. The real API is
  snapshot()/metadata()/search(). This module therefore implements
  get_sheet_intelligence() as an adapter that derives the operational morning
  fields (pending_tasks, staff_coverage, ...) from sheet_intelligence.snapshot().
- broadcast_to_supervisors() does NOT exist in task_delegation.py, and that module
  deliberately grants no outbound-message permissions. The honest equivalent is
  kept: deterministic draft -> explicit /confirm_supervisor_brief approval ->
  the owner forwards the final text (the bot never messages unauthorized chats).
- task_delegation IS integrated for deep-work triage: the dashboard surfaces the
  live delegation surface (/delegate, /mission) for المسار 3.
- The focus-block button creates a REAL Google Calendar proposal behind the
  existing /confirm_event approval gate; it never claims a booking without a
  receipt.

v2 additions:
- build_morning_briefing_dashboard(): spec entry point returning text +
  reply_markup, fed by live Sheets/Calendar evidence.
- handle_briefing_callback(chat_id, callback_data): dispatcher returning a
  status dict (await_input / needs_approval / success / unknown / error).
- 2x2 keyboard per spec: brain dump, supervisors broadcast (draft+approval),
  operations sheet (URL button when resolvable, callback fallback otherwise),
  and a 60-minute deep-focus block.
- Proactive mode (النظام الاستباقي): _maybe_send_morning_briefing() sends the
  dashboard once per morning (default 06:30-09:30 Riyadh) using the existing
  calendar-alert heartbeat in webhook AND polling mode, with a ledger file for
  de-duplication and MORNING_BRIEFING_AUTO=0 as a kill switch.
- Legacy v1 callback names (morning:*) remain accepted.

Reads are fail-soft; external writes stay behind explicit approval.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import time
from pathlib import Path

from connectors import sheet_intelligence as sheets
from connectors import life_domains

try:  # task_delegation is the live multi-agent surface (never required at import).
    from connectors import task_delegation as _team
except Exception:  # noqa: BLE001 - optional integration boundary
    _team = None

TASKS_TAB = os.environ.get("MORNING_TASKS_SHEET", "خطة الإنجاز والمهام").strip()
TASKS_TABS = (TASKS_TAB, "Projects")
SUPERVISOR_REPORTS_TAB = os.environ.get("MORNING_SUPERVISOR_SHEET", "تقارير المشرفين").strip()
BRAIN_DUMP_WINDOW_SECONDS = 600
SUPERVISOR_BRIEF_WINDOW_SECONDS = 900
FOCUS_BLOCK_MINUTES = 60
FOCUS_BLOCK_REMINDER_MINUTES = 5

DATA_DIR = Path(os.environ.get("AI_OS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
MORNING_LEDGER_NAME = "morning-briefing-ledger.json"

# Spec callback names (v2) + v1 legacy aliases for buttons already delivered.
CB_BRAIN_DUMP = "action_brain_dump"
CB_SUPERVISOR_BRIEF = "action_broadcast_supervisors"
CB_OPEN_TASKS = "action_open_tasks"
CB_FOCUS_BLOCK = "action_focus_block"
_LEGACY_CALLBACKS = {
    "morning:brain_dump": CB_BRAIN_DUMP,
    "morning:supervisor_brief": CB_SUPERVISOR_BRIEF,
    "morning:open_tasks": CB_OPEN_TASKS,
}

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
    r"لوحة\s+الصباح|لوحة\s+الفرز|صباح\s+الخير|morning\s+(?:brief|mode))"
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


def _now_local() -> dt.datetime:
    try:
        from connectors.calendar_actions import now_local

        return now_local()
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=3)))


def _today() -> dt.date:
    return _now_local().date()


def _now_text() -> str:
    now_fn = getattr(bot, "_now", None)
    if callable(now_fn):
        try:
            return str(now_fn())
        except Exception:
            pass
    return _now_local().isoformat(timespec="seconds")


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


def staff_pulse(clinics: list[dict]) -> str:
    """One-line operational pulse derived from the latest supervisor reports."""
    if not clinics:
        return "لا توجد تقارير جاهزية حديثة مؤكدة"
    red = [c["clinic"] for c in clinics if _readiness_severity(c.get("readiness")) == 0]
    yellow = [c["clinic"] for c in clinics if _readiness_severity(c.get("readiness")) == 1]
    if red:
        return "🔴 تحتاج تدخل الآن: " + "، ".join(red)
    if yellow:
        return "🟡 جاهزية جزئية تحتاج إغلاقًا اليوم: " + "، ".join(yellow)
    return "🟢 الجاهزية مستقرة حسب آخر تقارير المشرفين"


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


def get_sheet_intelligence() -> dict:
    """Spec-named data adapter over the REAL sheet_intelligence API.

    sheet_intelligence.py exposes snapshot()/metadata()/search(); it has no
    get_sheet_intelligence(). This adapter derives the morning operational
    fields from a live snapshot so callers get one typed payload:
      pending_tasks  — provenance-annotated overdue task lines
      staff_coverage — one-line clinics/staff pulse
      overdue/clinics — the structured evidence behind them
    Raises on a hard Sheets failure; callers decide fail-soft behavior.
    """
    data = _sheets_snapshot()
    overdue = overdue_tasks(data)
    clinics = clinic_readiness(data)
    return {
        "pending_tasks": [_item_summary(item) for item in overdue[:5]],
        "pending_count": len(overdue),
        "staff_coverage": staff_pulse(clinics),
        "overdue": overdue,
        "clinics": clinics,
    }


def morning_payload(events_limit: int = 8) -> dict:
    """Collect all morning dashboard sources; each source fails independently.

    Sheets evidence flows through get_sheet_intelligence() — the spec's data
    seam — so tests and future callers can inject one typed payload.
    """
    errors: list[str] = []
    overdue: list[dict] = []
    clinics: list[dict] = []
    staff = ""
    try:
        intel = get_sheet_intelligence()
        overdue = intel["overdue"]
        clinics = intel["clinics"]
        staff = intel["staff_coverage"]
    except Exception as exc:  # noqa: BLE001 - external Sheets boundary
        errors.append("Google Sheets: " + _safe_error(exc))
    events, calendar_error = today_clinic_events(limit=events_limit)
    if calendar_error:
        errors.append(calendar_error)
    return {
        "overdue": overdue,
        "clinics": clinics,
        "staff_coverage": staff or staff_pulse(clinics),
        "today_events": events,
        "errors": errors,
        "generated_at": _now_text(),
    }


def tasks_sheet_link() -> str:
    """Direct edit link to the operations/tasks tab; falls back to the workbook URL."""
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


def _safe_tasks_link() -> str:
    """URL for the sheet button; empty string when no valid http(s) link exists."""
    try:
        link = tasks_sheet_link()
    except Exception as exc:  # noqa: BLE001 - external Sheets boundary
        print(f"Tasks sheet link warning: {_safe_error(exc)}", flush=True)
        return ""
    return link if str(link).startswith(("https://", "http://")) else ""


# ---------------------------------------------------------------------------
# 2) Rendering — dashboard, keyboard, supervisor brief
# ---------------------------------------------------------------------------

def morning_keyboard() -> dict:
    """2x2 inline keyboard (spec layout).

    The sheet button is a native URL button when a valid link resolves
    (Telegram requires a raw URL — never a Markdown-wrapped string), and a
    callback button fallback otherwise.
    """
    tasks_button: dict = {"text": "📊 فتح شيت العمليات", "callback_data": CB_OPEN_TASKS}
    link = _safe_tasks_link()
    if link:
        tasks_button = {"text": "📊 فتح شيت العمليات", "url": link}
    return {
        "inline_keyboard": [
            [
                {"text": "🎙️ إفراغ ذهني سريع", "callback_data": CB_BRAIN_DUMP},
                {"text": "📢 بث توجيه المشرفين", "callback_data": CB_SUPERVISOR_BRIEF},
            ],
            [
                tasks_button,
                {"text": "⏱️ حجز وقت التركيز العميق", "callback_data": CB_FOCUS_BLOCK},
            ],
        ]
    }


def render_morning_dashboard(payload: dict) -> str:
    overdue = payload.get("overdue") or []
    clinics = payload.get("clinics") or []
    events = payload.get("today_events") or []
    errors = payload.get("errors") or []
    stamp = str(payload.get("generated_at") or "")[:16].replace("T", " ")

    lines = [
        "📋 لوحة الفرز والتوجيه التنفيذي الصباحي — التأهيل",
        f"⏱️ {stamp} (توقيت الرياض)",
        "",
        f"🏥 نبض الكوادر والعيادات: {payload.get('staff_coverage') or staff_pulse(clinics)}",
        "",
        f"⚠️ أبرز المهام المتأخرة المعلقة ({len(overdue)}):",
    ]
    if overdue:
        lines.extend("• " + _item_summary(item) for item in overdue[:3])
    else:
        lines.append("• لا توجد مهام متأخرة حرجة.")

    if overdue:
        domain_counts: dict[str, int] = {}
        for item in overdue:
            key = life_domains.classify_text(" | ".join(str(x) for x in (item.get("values") or [])))
            if key:
                domain_counts[key] = domain_counts.get(key, 0) + 1
        if domain_counts:
            ranked = sorted(
                domain_counts.items(),
                key=lambda kv: (-kv[1], life_domains.domain_order(kv[0])),
            )
            badges = " | ".join(f"{life_domains.badge(key)} {count}" for key, count in ranked[:3])
            lines.append(f"🧭 حسب الدائرة: {badges}")

    clinic_events = [event for event in events if event.get("is_clinic")]
    lines += ["", f"📅 مواعيد اليوم: {len(events)}" + (f" (منها {len(clinic_events)} للعيادات)" if events else "")]
    if events:
        for event in events[:3]:
            time_part = str(event.get("start") or "")[11:16]
            flag = " 🏥" if event.get("is_clinic") else ""
            lines.append(f"• {time_part or '—'} — {_redact_text(str(event.get('title') or '(بدون عنوان)'))[:80]}{flag}")
    else:
        lines.append("• لا توجد مواعيد مؤكدة لبقية اليوم.")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "▫️ المسار 1: النبض السريري وتغطية العيادات (PT / OT / ST)",
        "▫️ المسار 2: القرارات الإدارية السريعة (قاعدة الدقيقتين)",
        "▫️ المسار 3: العمل الاستراتيجي العميق (الرعاية المنزلية / MyoMentor)",
        "▫️ المسار 4: التنسيق وبث التوجيهات للمشرفين",
    ]
    if _team is not None:
        lines.append("🤖 لتفويض عمل عميق للفريق: /delegate auto الهدف أو /mission deep الهدف")
    if errors:
        lines += ["", "⚠️ مصادر متعذرة (استُكملت البقية): " + "؛ ".join(str(x)[:120] for x in errors[:2])]
    lines += ["", "اختر من الأزرار بالأسفل 👇"]
    return "\n".join(lines)[:3500]


def build_morning_briefing_dashboard() -> dict:
    """Spec entry point: live triage text + interactive keyboard.

    Returns {"text", "reply_markup"}; plain text is intentional (no parse_mode)
    because the repo's Telegram style avoids Markdown parsing failures with
    Arabic content. Never raises: a data failure returns a safe dashboard.
    """
    try:
        payload = morning_payload()
        return {
            "text": render_morning_dashboard(payload),
            "reply_markup": morning_keyboard(),
        }
    except Exception as exc:  # noqa: BLE001 - keep the morning flow non-raising
        safe = _safe_error(exc)
        print(f"Morning dashboard build error: {safe}", flush=True)
        return {
            "text": "⚠️ تعذر تجهيز التوجيه الصباحي بسبب خطأ في قراءة البيانات: " + safe,
            "reply_markup": {"inline_keyboard": []},
        }


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
        lines.append("• تحديث حالة المهام المتأخرة المذكورة أعلاه في شيت العمليات اليوم مع ذكر السبب.")
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


def _cb_supervisor_brief(chat_id: int) -> str:
    """Build the deterministic draft and register its approval token."""
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
    return token


def _cb_open_tasks(chat_id: int):
    _typing(chat_id)
    lines = ["📊 شيت العمليات", tasks_sheet_link(), ""]
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


def _next_focus_start(now: dt.datetime) -> dt.datetime:
    """Round up to the next 5-minute boundary so the block never starts in the past."""
    base = now.replace(second=0, microsecond=0)
    base += dt.timedelta(minutes=5 - (base.minute % 5))
    if base <= now:
        base += dt.timedelta(minutes=5)
    return base


def _cb_focus_block(chat_id: int) -> dict:
    """Propose a REAL 60-minute deep-focus Calendar event behind approval.

    The event is only created after the owner approves via the existing
    /confirm_event gate (mobile-runtime also allows a bare /confirm_event when
    exactly one proposal is pending). No booking is claimed before a receipt.
    """
    try:
        now = _now_local()
        start = _next_focus_start(now)
        end = start + dt.timedelta(minutes=FOCUS_BLOCK_MINUTES)
        proposal = {
            "title": "⏱️ تركيز عميق — التوجيه الصباحي",
            "start": start,
            "end": end,
            "reminder_minutes": FOCUS_BLOCK_REMINDER_MINUTES,
        }
        token = secrets.token_hex(3)
        pending = getattr(bot, "_PENDING_CALENDAR_EVENTS", None)
        if pending is None:
            raise RuntimeError("Calendar approval queue غير متاح في هذه البيئة")
        pending[token] = {
            "proposal": proposal,
            "chat_id": str(chat_id),
            "expires": time.time() + 900,
        }
        message = (
            "⏱️ معاينة حجز وقت التركيز العميق — لم يُضف بعد\n"
            f"البداية: {start.strftime('%Y-%m-%d %H:%M')}\n"
            f"النهاية: {end.strftime('%Y-%m-%d %H:%M')}\n"
            f"المدة: {FOCUS_BLOCK_MINUTES} دقيقة | التنبيه: قبل {FOCUS_BLOCK_REMINDER_MINUTES} دقائق\n\n"
            f"للاعتماد خلال 15 دقيقة:\n/confirm_event {token}"
        )
        bot.send(chat_id, message)
        return {"status": "needs_approval", "message": f"معاينة الحجز جاهزة؛ الاعتماد: /confirm_event {token}"}
    except Exception as exc:  # noqa: BLE001 - Calendar/proposal boundary
        safe = _safe_error(exc)
        print(f"Focus block proposal error: {safe}", flush=True)
        bot.send(chat_id, "❌ تعذر تجهيز حجز وقت التركيز: " + safe[:220])
        return {"status": "error", "message": "تعذر تجهيز حجز وقت التركيز: " + safe[:150]}


def handle_briefing_callback(chat_id: int, callback_data: str) -> dict:
    """Dispatch a morning-dashboard button press and return its outcome.

    Statuses: await_input (brain dump), needs_approval (broadcast draft /
    focus block), success (sheet link), unknown, error. Side-effect messages
    are sent to the chat by the action implementations themselves.
    """
    data = _LEGACY_CALLBACKS.get(str(callback_data or ""), str(callback_data or ""))
    try:
        if data == CB_BRAIN_DUMP:
            _cb_brain_dump(int(chat_id))
            return {"status": "await_input", "message": "🎙️ وضع الإفراغ الذهني مفتوح (10 دقائق). أرسل المهام نصًا أو صوتًا."}
        if data == CB_SUPERVISOR_BRIEF:
            token = _cb_supervisor_brief(int(chat_id))
            return {"status": "needs_approval", "message": f"📢 المسودة جاهزة؛ للاعتماد: /confirm_supervisor_brief {token}"}
        if data == CB_FOCUS_BLOCK:
            return _cb_focus_block(int(chat_id))
        if data == CB_OPEN_TASKS:
            _cb_open_tasks(int(chat_id))
            return {"status": "success", "message": "📊 تم إرسال رابط شيت العمليات مع المهام المتأخرة."}
        return {"status": "unknown", "message": "أمر غير معروف؛ افتح اللوحة من جديد عبر /morning."}
    except Exception as exc:  # noqa: BLE001 - action boundary
        safe = _safe_error(exc)
        print(f"Briefing callback error [{data}]: {safe}", flush=True)
        return {"status": "error", "message": "❌ تعذر التنفيذ: " + safe[:150]}


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
        data = _LEGACY_CALLBACKS.get(str(callback_query.get("data") or ""), str(callback_query.get("data") or ""))
        if data not in {CB_BRAIN_DUMP, CB_SUPERVISOR_BRIEF, CB_FOCUS_BLOCK, CB_OPEN_TASKS}:
            answer("⚠️ زر غير معروف؛ افتح اللوحة من جديد عبر /morning.")
            return
        answer("⏳ جارٍ التنفيذ...")
        handle_briefing_callback(int(chat_id), data)
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
    """Render the interactive morning dashboard with the spec buttons."""
    _typing(chat_id)
    dashboard = build_morning_briefing_dashboard()
    send_with_keyboard(chat_id, dashboard["text"], dashboard["reply_markup"])


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
# 5) Proactive mode — automatic daily morning send
# ---------------------------------------------------------------------------

def _parse_clock(value: str, default: dt.time) -> dt.time:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    if not match:
        return default
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return dt.time(hour, minute)
    return default


def _send_window() -> tuple[dt.time, dt.time]:
    start = _parse_clock(os.environ.get("MORNING_BRIEFING_SEND_AFTER", "06:30"), dt.time(6, 30))
    end = _parse_clock(os.environ.get("MORNING_BRIEFING_SEND_BEFORE", "09:30"), dt.time(9, 30))
    if end <= start:
        end = dt.time(start.hour + 1, start.minute) if start.hour < 23 else dt.time(23, 59)
    return start, end


def _proactive_enabled() -> bool:
    return os.environ.get("MORNING_BRIEFING_AUTO", "1").strip().lower() not in {"0", "false", "off", "no"}


def _ledger_file() -> Path:
    return Path(DATA_DIR) / MORNING_LEDGER_NAME


def _already_sent_today(day: dt.date) -> bool:
    try:
        payload = json.loads(_ledger_file().read_text(encoding="utf-8"))
        return str(payload.get("last_sent", "")) == day.isoformat()
    except (OSError, ValueError, TypeError):
        return False


def _mark_sent(day: dt.date):
    try:
        path = _ledger_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_sent": day.isoformat()}), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"Morning ledger write warning: {exc}", flush=True)


def _maybe_send_morning_briefing(now: dt.datetime | None = None, force: bool = False):
    """Send the dashboard to the owner once per morning (proactive mode).

    Rides the existing calendar-alert heartbeat (webhook worker + polling
    loop). `force` bypasses the time window only; the once-per-day ledger
    de-duplication always applies. A build/send failure is still marked as
    sent for the day: the owner gets one honest failure notice instead of a
    retry every heartbeat.
    """
    if bot is None or not _proactive_enabled():
        return False
    now = now or _now_local()
    if not force:
        start, end = _send_window()
        if not (start <= now.time() <= end):
            return False
    owner = getattr(bot, "_owner_id", lambda: "")()
    if not owner:
        return False
    if _already_sent_today(now.date()):
        return False
    try:
        dashboard = build_morning_briefing_dashboard()
        send_with_keyboard(int(owner), dashboard["text"], dashboard["reply_markup"])
        return True
    except Exception as exc:  # noqa: BLE001 - Telegram boundary
        print(f"Proactive morning briefing warning: {_safe_error(exc)}", flush=True)
        return False
    finally:
        _mark_sent(now.date())


# ---------------------------------------------------------------------------
# 6) Installation — wraps the live bot module (webhook + polling modes)
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
    """Attach Morning Briefing Mode v2 to the live bot module.

    Idempotent (guarded by _morning_briefing_installed). Installs cleanly in
    webhook mode (called at the bottom of connectors/telegram_bot.py, wrapping
    the outermost handle_message) and in polling mode. The proactive daily
    send is chained onto the calendar-alert heartbeat so both modes get it
    without new infrastructure.
    """
    global bot
    bot = bot_module
    if getattr(bot_module, "_morning_briefing_installed", False):
        return bot_module

    original_handle = bot_module.handle_message
    original_configure = bot_module.configure_commands
    original_start = bot_module.command_start
    original_alerts = getattr(bot_module, "_maybe_send_calendar_alerts", None)

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
                    + (
                        "🤖 لتحويل أي ملاحظة إلى مهمة مفوضة: /delegate auto <الملاحظة>\n"
                        if _team is not None else ""
                    )
                    + "افتح لوحة جديدة في أي وقت عبر /morning.",
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
            "بث توجيه المشرفين، شيت العمليات، وحجز وقت التركيز العميق",
        )

    def _maybe_send_calendar_alerts():
        # Chain the proactive morning send onto the existing heartbeat so both
        # webhook and polling modes trigger it without new infrastructure.
        if callable(original_alerts):
            original_alerts()
        try:
            _maybe_send_morning_briefing()
        except Exception as exc:  # noqa: BLE001 - heartbeat must never die
            print(f"Morning heartbeat warning: {_safe_error(exc)}", flush=True)

    bot_module.handle_message = handle_message
    bot_module.handle_callback_query = handle_callback_query
    bot_module.handle_briefing_callback = handle_briefing_callback
    bot_module.command_morning = command_morning
    bot_module.command_confirm_supervisor_brief = command_confirm_supervisor_brief
    bot_module.configure_commands = configure_commands
    bot_module.command_start = command_start
    if callable(original_alerts):
        bot_module._maybe_send_calendar_alerts = _maybe_send_calendar_alerts
    bot_module._morning_briefing_installed = True
    return bot_module

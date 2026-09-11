# -*- coding: utf-8 -*-
"""Approval-safe proactive Chief of Staff controller.

The controller is deliberately separate from Calendar intent routing. It reads
confirmed state, produces evidence-backed proposals, applies the pilot budget and
quiet hours, and leaves delivery/logging to ``proactive_worker``.

It never sends to a third party and it never treats a plan as proof of completion.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
from zoneinfo import ZoneInfo

try:
    from .store import Store
except ImportError:  # direct ``python engine/...`` execution
    from store import Store

TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))

def _today(now: dt.datetime | None = None) -> dt.date:
    value = now or dt.datetime.now(TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(TZ).date()


def _now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def _iso(value: dt.datetime | dt.date | None = None) -> str:
    if value is None:
        return _now().isoformat(timespec="seconds")
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value.isoformat()
    return value.isoformat(timespec="seconds")


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _parse_hhmm(value: str | None) -> dt.time | None:
    if not value:
        return None
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(value).strip())
    if not match:
        return None
    return dt.time(int(match.group(1)), int(match.group(2)))


def _in_quiet_hours(now: dt.datetime, config: dict) -> bool:
    current = now.time().replace(second=0, microsecond=0)
    start = _parse_hhmm(config.get("quiet_start")) or dt.time(22, 0)
    end = _parse_hhmm(config.get("quiet_end")) or dt.time(5, 15)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def default_config(now: dt.datetime | None = None) -> dict:
    """Return safe defaults; automatic delivery remains disabled by default."""
    start = _today(now)
    return {
        "enabled": False,
        # Explicit two-person/owner approval gate; code and env alone cannot
        # accidentally turn the Pilot live before the T3 decision.
        "t3_approved": False,
        "pilot_start": start.isoformat(),
        "pilot_days": 14,
        "max_alerts_per_day": 3,
        "quiet_start": "22:00",
        "quiet_end": "05:15",
        "exercise_time": "05:30",
        # The four exercise weekdays were not supplied; empty means no guessing.
        "exercise_weekdays": [],
        "reading_time": "07:00",
        # Python weekday: Sunday=6, Monday=0 ... Thursday=3.
        "reading_weekdays": [6, 0, 1, 2, 3],
        "executive_time": "06:00",
        "weekly_review_weekday": 6,
        "weekly_review_time": "08:00",
        "relationship_threshold_days": 7,
        # No relationship dispatch time was approved; the worker may use the
        # first allowed cycle once a confirmed last-contact date exists.
        "relationship_check_time": None,
    }


class StoreProxy:
    """Read-only adapter used when a pure function receives a state dict."""

    def __init__(self, data: dict):
        self.data = data


def get_config(store: Store | StoreProxy | None = None, now: dt.datetime | None = None) -> dict:
    store = store or Store()
    config = default_config(now)
    saved = store.data.get("proactive_config") or {}
    config.update(copy.deepcopy(saved))
    return config


def configure(values: dict, store: Store | None = None, now: dt.datetime | None = None) -> dict:
    """Persist only known configuration keys; no delivery is enabled implicitly."""
    store = store or Store()
    allowed = set(default_config(now))
    clean = {key: value for key, value in values.items() if key in allowed}
    if "max_alerts_per_day" in clean:
        clean["max_alerts_per_day"] = max(1, min(3, int(clean["max_alerts_per_day"])))
    if "pilot_days" in clean:
        clean["pilot_days"] = max(1, min(31, int(clean["pilot_days"])))
    for key in ("quiet_start", "quiet_end", "exercise_time", "reading_time", "executive_time", "weekly_review_time"):
        if key in clean and _parse_hhmm(clean[key]) is None:
            raise ValueError(f"invalid proactive time: {key}")
    if "relationship_check_time" in clean and clean["relationship_check_time"] is not None:
        if _parse_hhmm(clean["relationship_check_time"]) is None:
            raise ValueError("invalid relationship_check_time")

    def mutate(state):
        current = dict(state.get("proactive_config") or {})
        current.update(clean)
        state["proactive_config"] = current
        return True, current

    return store.transaction(mutate, "proactive_configure", keys=sorted(clean))


def _hash(*parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _source_date(item: dict, fallback: dt.date | None = None) -> str:
    for key in ("date", "created_at", "updated_at", "التاريخ", "آخر تحديث", "since"):
        value = _date(item.get(key))
        if value:
            return value.isoformat()
    return "غير مؤرخ"


def _evidence(source: str, detail: str, date_value: str) -> list[dict]:
    return [{"source": source, "date": date_value, "detail": str(detail)[:500]}]


def _alert(alert_id: str, kind: str, reason: str, evidence: list[dict], action: str,
           title: str = "اقتراح استباقي") -> dict:
    return {
        "alert_id": alert_id,
        "kind": kind,
        "title": title,
        "reason": reason,
        "evidence": evidence,
        "action": action,
        "options": ["تم", "أجّل", "تجاهل"],
    }


def _event_done(events: list[dict], kind: str, day: dt.date, person: str = "") -> bool:
    for event in events:
        if event.get("kind") != kind or str(event.get("status", "")).upper() not in {"DONE", "تم", "COMPLETED"}:
            continue
        if _date(event.get("at")) != day:
            continue
        if person and str(event.get("person", "")).strip() != person:
            continue
        return True
    return False


def record_event(kind: str, status: str = "DONE", person: str = "",
                 detail: str = "", at: dt.datetime | None = None,
                 store: Store | None = None) -> dict:
    store = store or Store()
    event = {
        "event_id": "PE-" + _hash(kind, person, detail, _iso(at)),
        "kind": kind,
        "status": status,
        "person": person,
        "detail": detail[:500],
        "at": _iso(at),
    }

    def mutate(state):
        events = state.setdefault("proactive_events", [])
        if any(row.get("event_id") == event["event_id"] for row in events):
            return False, event
        events.append(event)
        return True, event

    return store.transaction(mutate, "proactive_event", kind=kind, person=person)


def _active_items(state: dict, section: str) -> list[dict]:
    rows = state.get(section) or []
    return [row for row in rows if isinstance(row, dict)]


def _contextual_suggestions(state: dict, now: dt.datetime, limit: int = 1,
                             external_evidence: list[dict] | None = None) -> list[dict]:
    """Produce deterministic, evidence-backed suggestions from historical state."""
    today = now.date()
    tasks = _active_items(state, "tasks")
    meetings = _active_items(state, "meetings")
    decisions = _active_items(state, "decisions")
    events = _active_items(state, "proactive_events")
    suggestions = []

    def learning_done(title: str) -> bool:
        title_text = str(title).strip().lower()
        return any(
            event.get("kind") == "learning"
            and str(event.get("status", "")).upper() in {"DONE", "COMPLETED", "تم"}
            and title_text
            and title_text in str(event.get("detail", "")).lower()
            for event in events
        )

    # Waiting/blocked records are higher-signal than a generic productivity tip.
    for section in ("blockers", "waiting_for", "projects", "tasks"):
        for item in _active_items(state, section):
            status = str(item.get("status") or item.get("الحالة") or "").strip().lower()
            if status not in {"waiting", "overdue", "blocked", "عالق", "انتظار", "متأخر", "متوقف"}:
                continue
            title = item.get("item") or item.get("task") or item.get("title") or item.get("العنوان") or "عائق مفتوح"
            source_date = _source_date(item, today)
            suggestions.append(_alert(
                "PA-" + _hash("blocker", section, title, source_date),
                "blocker",
                "يوجد عائق أو انتظار مفتوح يحتاج خطوة فك واحدة.",
                _evidence(f"StateStore.{section}", str(title), source_date),
                "حدد مالك الخطوة التالية وموعدًا واحدًا لفك العائق أو اطلب معلومة محددة.",
                "اقتراح فك عائق",
            ))
            break
        if suggestions:
            break

    for task in tasks:
        if suggestions:
            break
        status = str(task.get("status") or task.get("الحالة") or "").strip().lower()
        owner = task.get("owner") or task.get("المسؤول") or task.get("assigned_to") or task.get("من المسؤول")
        due = task.get("due") or task.get("الموعد النهائي") or task.get("deadline")
        if status in {"منجزة", "مكتمل", "completed", "done"}:
            continue
        if not owner or not due:
            title = task.get("title") or task.get("العنوان") or task.get("task") or "مهمة متكررة"
            source_date = _source_date(task, today)
            suggestions.append(_alert(
                "PA-" + _hash("missing-owner-deadline", title, source_date),
                "contextual_suggestion",
                "مهمة مفتوحة بلا مسؤول أو موعد مكتمل.",
                _evidence("StateStore.tasks", str(title), source_date),
                "اختر مهمة واحدة وسجّل لها مالكًا ومعيار نجاح وموعدًا واضحًا.",
                "اقتراح إداري",
            ))
            break

    if not suggestions:
        for meeting in meetings:
            text = " ".join(str(meeting.get(key, "")) for key in
                             ("title", "الموضوع", "notes", "الملاحظات", "summary", "الملخص"))
            if re.search(r"تفويض|delegat|وقت|time|نتيجة|result|okr|هدف", text, re.I):
                source_date = _source_date(meeting, today)
                suggestions.append(_alert(
                    "PA-" + _hash("meeting-signal", text, source_date),
                    "contextual_suggestion",
                    "ظهرت إشارة إدارية في نقطة اجتماع سابقة.",
                    _evidence("StateStore.meetings", text[:450], source_date),
                    "اختر نتيجة واحدة من الاجتماع وحوّلها إلى إجراء بمالك وموعد.",
                    "اقتراح بعد مراجعة اجتماع",
                ))
                break

    if not suggestions:
        for decision in decisions:
            status = str(decision.get("status") or decision.get("الحالة") or "").lower()
            if status not in {"resolved", "closed", "منجز", "مغلق", "محسوم"}:
                text = decision.get("title") or decision.get("الموضوع") or decision.get("decision") or "قرار مفتوح"
                source_date = _source_date(decision, today)
                suggestions.append(_alert(
                    "PA-" + _hash("open-decision", text, source_date),
                    "contextual_suggestion",
                    "يوجد قرار مفتوح يحتاج حسمًا أو خطوة تالية.",
                    _evidence("StateStore.decisions", str(text), source_date),
                    "حدد خيارًا واحدًا للقرار أو سجّل المعلومة الناقصة التي تمنع الحسم.",
                    "اقتراح قرار",
                ))
                break

    if not suggestions:
        for section in ("learning", "knowledge_sources", "content_sources"):
            for item in _active_items(state, section):
                status = str(item.get("status") or item.get("الحالة") or "").strip().lower()
                if status in {"done", "completed", "complete", "مكتمل", "منجز", "reference", "مرجع"}:
                    continue
                title = (item.get("title") or item.get("source") or item.get("العنوان") or
                         item.get("channel") or item.get("name"))
                if not title or learning_done(title):
                    continue
                if section == "content_sources" and not (item.get("status") or item.get("next_action")):
                    # The seeded YouTube list is a catalogue, not evidence that a
                    # specific video was assigned or missed.
                    continue
                source_date = _source_date(item, today)
                suggestions.append(_alert(
                    "PA-" + _hash("learning", section, title, source_date),
                    "learning",
                    "توجد مادة تعلم مسجلة لم تُثبت مراجعتها بعد.",
                    _evidence(f"StateStore.{section}", str(title), source_date),
                    "اختر مادة واحدة، راجعها، وسجّل فكرة قابلة للتطبيق ودليلًا واحدًا.",
                    "اقتراح تعلم",
                ))
                break
            if suggestions:
                break

    if not suggestions and external_evidence:
        item = external_evidence[0]
        suggestions.append(_alert(
            "PA-" + _hash("external", item.get("source"), item.get("date"), item.get("signal")),
            "contextual_suggestion",
            "ظهرت إشارة مرتبطة بموضوع إداري في مصدر خارجي موصول.",
            _evidence(item.get("source", "Google Sheets"), item.get("signal", "إشارة موثقة"), item.get("date", "غير مؤرخ")),
            "راجع المصدر وحدد إجراءً واحدًا مرتبطًا بالإشارة.",
            "اقتراح من السياق الموصول",
        ))
    return suggestions[:max(1, limit)]


def due_alerts(state: dict, now: dt.datetime | None = None, include_context: bool = False,
               external_evidence: list[dict] | None = None) -> list[dict]:
    now = _now(now)
    config = get_config(StoreProxy(state), now)
    day = now.date()
    events = _active_items(state, "proactive_events")
    alerts = []

    def due(rule_time: str | None, weekday: int | None = None) -> bool:
        target = _parse_hhmm(rule_time)
        if target is None or now.time().replace(second=0, microsecond=0) != target:
            return False
        return weekday is None or day.weekday() == int(weekday)

    if due(config.get("executive_time")):
        tasks = _active_items(state, "tasks")
        alerts.append(_alert(
            "PA-" + _hash("executive", day.isoformat()),
            "executive_brief",
            "حل وقت الملخص التنفيذي اليومي.",
            _evidence("StateStore", f"مهام مسجلة: {len(tasks)}", day.isoformat()),
            "اعرض الملخص التنفيذي، وحدد أولوية واحدة لليوم.",
            "الملخص التنفيذي",
        ))

    weekdays = config.get("reading_weekdays") or []
    if due(config.get("reading_time"), day.weekday()) and day.weekday() in weekdays:
        if not _event_done(events, "reading", day):
            alerts.append(_alert(
                "PA-" + _hash("reading", day.isoformat()),
                "reading",
                "حل وقت جلسة القراءة ولم يوجد سجل قراءة فعلي لهذا اليوم.",
                _evidence("proactive_events", "لا يوجد حدث reading=done لهذا اليوم", day.isoformat()),
                "نفّذ جلسة القراءة وسجّلها أو أجّلها.",
                "جلسة القراءة",
            ))

    exercise_days = config.get("exercise_weekdays") or []
    if due(config.get("exercise_time"), day.weekday()) and day.weekday() in exercise_days:
        if not _event_done(events, "exercise", day):
            alerts.append(_alert(
                "PA-" + _hash("exercise", day.isoformat()),
                "exercise",
                "حل وقت جلسة التمرين ولم يوجد سجل تمرين فعلي لهذا اليوم.",
                _evidence("proactive_events", "لا يوجد حدث exercise=done لهذا اليوم", day.isoformat()),
                "نفّذ جلسة التمرين وسجّلها أو أجّلها.",
                "جلسة التمرين",
            ))

    if due(config.get("weekly_review_time"), config.get("weekly_review_weekday")):
        alerts.append(_alert(
            "PA-" + _hash("weekly-review", day.isoformat()),
            "weekly_review",
            "حل وقت المراجعة الأسبوعية.",
            _evidence("proactive_alerts", f"تنبيهات مسجلة: {len(_active_items(state, 'proactive_alerts'))}", day.isoformat()),
            "اعرض عدد المهام والتنبيهات والاستجابات والتأخيرات واقترح تعديلًا واحدًا فقط.",
            "المراجعة الأسبوعية",
        ))

    # Relationship alerts require a confirmed last-contact date. Unknown is never
    # treated as seven days overdue.
    threshold = int(config.get("relationship_threshold_days", 7) or 7)
    contacts = _active_items(state, "contacts")
    relationship_time = config.get("relationship_check_time")
    if relationship_time and due(relationship_time):
        for contact in contacts:
            person = str(contact.get("name") or contact.get("الاسم") or contact.get("person") or "").strip()
            last = _date(contact.get("last_contact") or contact.get("آخر تواصل") or contact.get("last_contact_at"))
            if not person or not last or (day - last).days < threshold:
                continue
            if not _event_done(events, "contact", last, person):
                alerts.append(_alert(
                    "PA-" + _hash("contact", person, last.isoformat()),
                    "relationship",
                    f"مرّ {(day - last).days} يومًا منذ آخر تواصل مسجّل مع {person}.",
                    _evidence("StateStore.contacts", f"آخر تواصل مع {person}: {last.isoformat()}", last.isoformat()),
                    f"راجع ما إذا كنت تريد التواصل مع {person}، دون إرسال رسالة تلقائيًا.",
                    "مراجعة علاقة",
                ))
                break

    if include_context:
        alerts.extend(_contextual_suggestions(
            state, now, limit=1, external_evidence=external_evidence
        ))
    return alerts


def _alert_count_today(state: dict, day: dt.date) -> int:
    count = 0
    for row in _active_items(state, "proactive_alerts"):
        if _date(row.get("created_at")) == day and row.get("status") not in {"CANCELLED", "LOG_FAILED"}:
            count += 1
    return count


def claim_alert(alert: dict, now: dt.datetime | None = None, store: Store | None = None) -> bool:
    now = _now(now)
    store = store or Store()
    config = get_config(store, now)
    alert_id = alert["alert_id"]

    def mutate(state):
        ledger = state.setdefault("proactive_alerts", [])
        if any(row.get("alert_id") == alert_id for row in ledger):
            return False, False
        if _alert_count_today(state, now.date()) >= int(config.get("max_alerts_per_day", 3) or 3):
            return False, False
        row = dict(alert)
        row.update({"created_at": _iso(now), "status": "CLAIMED", "responses": []})
        ledger.append(row)
        return True, True

    return bool(store.transaction(mutate, "proactive_alert_claim", alert_id=alert_id))


def mark_alert(alert_id: str, status: str, detail: str = "", store: Store | None = None) -> bool:
    store = store or Store()

    def mutate(state):
        for row in state.setdefault("proactive_alerts", []):
            if row.get("alert_id") == alert_id:
                row["status"] = status
                row["status_at"] = _iso()
                if detail:
                    row["status_detail"] = detail[:500]
                return True, True
        return False, False

    return bool(store.transaction(mutate, "proactive_alert_status", alert_id=alert_id, status=status))


def record_response(alert_id: str, response: str, store: Store | None = None) -> dict:
    normalized = str(response or "").strip()
    mapping = {"done": "تم", "snooze": "أجّل", "ignore": "تجاهل", "اجل": "أجّل"}
    normalized = mapping.get(normalized.lower(), normalized)
    if normalized not in {"تم", "أجّل", "تجاهل"}:
        raise ValueError("response must be one of: تم / أجّل / تجاهل")
    store = store or Store()
    response_row = {"response": normalized, "at": _iso()}

    def mutate(state):
        for row in state.setdefault("proactive_alerts", []):
            if row.get("alert_id") == alert_id:
                row.setdefault("responses", []).append(response_row)
                row["last_response"] = normalized
                row["last_response_at"] = response_row["at"]
                row["status"] = "RESPONDED"
                return True, {"alert": copy.deepcopy(row), "response": response_row}
        return False, None

    result = store.transaction(mutate, "proactive_response", alert_id=alert_id, response=normalized)
    if not result:
        raise ValueError("unknown proactive alert_id")
    return result


def followup_row(alert: dict, event: str, response: str = "") -> list:
    evidence = json.dumps(alert.get("evidence", []), ensure_ascii=False, separators=(",", ":"))
    return [
        _iso(), alert.get("alert_id", ""), event, alert.get("kind", ""),
        str(alert.get("reason", ""))[:500], evidence[:3000],
        str(alert.get("action", ""))[:500], response, "telegram_owner", "PROACTIVE_PILOT",
    ]


def format_alert(alert: dict) -> str:
    evidence = alert.get("evidence") or []
    evidence_text = "\n".join(
        f"• {item.get('source', 'غير محدد')} — {item.get('date', 'غير محدد')}: {item.get('detail', '')}"
        for item in evidence
    ) or "• لا توجد بيانات مؤكدة"
    return (
        f"🔎 {alert.get('title', 'اقتراح استباقي')}\n\n"
        f"الإشارة: {alert.get('reason', '')}\n\n"
        f"الدليل:\n{evidence_text}\n\n"
        f"الإجراء الواحد: {alert.get('action', '')}\n\n"
        "الخيارات: تم / أجّل / تجاهل\n"
        f"المعرّف: {alert.get('alert_id', '')}"
    )


def status(store: Store | None = None, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    store = store or Store()
    config = get_config(store, now)
    alerts = _active_items(store.data, "proactive_alerts")
    events = _active_items(store.data, "proactive_events")
    pilot_start = _date(config.get("pilot_start"))
    pilot_end = pilot_start + dt.timedelta(days=int(config.get("pilot_days", 14)) - 1) if pilot_start else None
    return {
        "enabled": bool(config.get("enabled")),
        "t3_approved": bool(config.get("t3_approved")),
        "pilot_start": pilot_start.isoformat() if pilot_start else "",
        "pilot_end": pilot_end.isoformat() if pilot_end else "",
        "alerts_today": _alert_count_today(store.data, now.date()),
        "max_alerts_per_day": int(config.get("max_alerts_per_day", 3)),
        "quiet_hours": f"{config.get('quiet_start', '22:00')}-{config.get('quiet_end', '05:15')}",
        "events": len(events),
        "alerts": len(alerts),
        "exercise_days_configured": bool(config.get("exercise_weekdays")),
        "relationship_time_configured": bool(config.get("relationship_check_time")),
        "automatic_delivery": (
            bool(config.get("enabled")) and bool(config.get("t3_approved"))
            and not _in_quiet_hours(now, config)
        ),
    }


def render_status(data: dict) -> str:
    return (
        "🧭 الطبقة الاستباقية\n"
        f"الحالة: {'مفعّلة' if data['enabled'] and data['t3_approved'] else 'موقوفة — تنتظر اعتماد T3' if not data['t3_approved'] else 'غير مفعّلة'}\n"
        f"اعتماد T3: {'نعم' if data['t3_approved'] else 'لا'}\n"
        f"Pilot: {data['pilot_start']} → {data['pilot_end']}\n"
        f"تنبيهات اليوم: {data['alerts_today']}/{data['max_alerts_per_day']}\n"
        f"ساعات الهدوء: {data['quiet_hours']}\n"
        f"سجلات الأحداث: {data['events']} | سجلات التنبيهات: {data['alerts']}\n"
        f"أيام التمرين: {'محددة' if data['exercise_days_configured'] else 'غير محددة — لن أفترضها'}\n"
        f"التحقق من العلاقات: {'مهيأ' if data['relationship_time_configured'] else 'ينتظر وقتًا معتمدًا'}\n"
        "الإرسال لطرف آخر: معطل دائمًا؛ مسودة PROPOSE فقط"
    )


def render_proposals(alerts: list[dict]) -> str:
    if not alerts:
        return "لا توجد إشارة مؤكدة أو قاعدة مستحقة الآن. لم أستنتج نشاطًا غير مسجل."
    return "\n\n".join(format_alert(alert) for alert in alerts[:3])


def collect(now: dt.datetime | None = None, store: Store | None = None,
            include_context: bool = False, external_evidence: list[dict] | None = None,
            respect_quiet: bool = True) -> list[dict]:
    store = store or Store()
    now = _now(now)
    config = get_config(store, now)
    if respect_quiet and _in_quiet_hours(now, config):
        return []
    start = _date(config.get("pilot_start"))
    if start:
        end = start + dt.timedelta(days=int(config.get("pilot_days", 14)) - 1)
        if not start <= now.date() <= end:
            return []
    return due_alerts(
        store.data, now, include_context=include_context,
        external_evidence=external_evidence,
    )

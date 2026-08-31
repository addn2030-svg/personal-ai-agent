# -*- coding: utf-8 -*-
"""Deadline + reminder + report extension for Natural Action Executor.

Scope:
- accepts only unambiguous deadline phrases (ISO date or today/tomorrow + explicit time);
- stores the project deadline in the live Projects sheet after approval;
- creates one Calendar deadline reminder only after approval;
- returns a compact Telegram execution report/receipt;
- supports read-only `/report` / `ارسل تقرير ...` without model calls.

This deliberately does not duplicate the broader weekday Calendar parser from PR #50.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from connectors import action_executor as base
from connectors import calendar_actions
from connectors import sheet_intelligence as sheets
from engine.store import Store

TZ = ZoneInfo("Asia/Riyadh")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DEADLINE_HINT = re.compile(r"الموعد\s+النهائي|آخر\s+موعد|اخر\s+موعد|deadline", re.I)
_REPORT_RE = re.compile(r"^(?:ارسل|أرسل|اعرض|أعرض)\s+تقرير(?:\s+عن)?\s*(.*)$|^report\s*(.*)$", re.I)
_MONTHS_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]
_DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

_ORIGINAL_BUILD_PLAN = None
_ORIGINAL_CREATE_PREVIEW = None
_ORIGINAL_RENDER_PREVIEW = None
_ORIGINAL_EXECUTE = None
_ORIGINAL_RENDER_RECEIPT = None
_INSTALLED = False


def _now(base_now: dt.datetime | None = None) -> dt.datetime:
    if base_now is None:
        return dt.datetime.now(TZ)
    if base_now.tzinfo is None:
        return base_now.replace(tzinfo=TZ)
    return base_now.astimezone(TZ)


def _parse_clock(text: str) -> tuple[int, int] | None:
    value = (text or "").translate(_AR_DIGITS)
    matches = list(re.finditer(
        r"(?:الساعة|الساعه|at)\s*(\d{1,2})(?::(\d{2}))?\s*"
        r"(صباحا|صباحًا|صباح|ص|am|مساء|مساءً|مساءا|م|pm)?",
        value, re.I,
    ))
    clocks = []
    for match in matches:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = (match.group(3) or "").lower()
        if minute > 59 or hour > 23:
            raise ValueError("NEEDS_INPUT: الوقت غير صالح.")
        if period in {"مساء", "مساءً", "مساءا", "م", "pm"} and hour < 12:
            hour += 12
        if period in {"صباحا", "صباحًا", "صباح", "ص", "am"} and hour == 12:
            hour = 0
        clocks.append((hour, minute))
    unique = list(dict.fromkeys(clocks))
    if len(unique) > 1:
        raise ValueError("NEEDS_INPUT: وجدت أكثر من وقت للموعد النهائي؛ حدد وقتًا واحدًا.")
    return unique[0] if unique else None


def _parse_deadline(text: str, base_now: dt.datetime | None = None) -> dt.datetime | None:
    value = (text or "").translate(_AR_DIGITS)
    if not _DEADLINE_HINT.search(value):
        return None
    now = _now(base_now)

    iso_dates = list(dict.fromkeys(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", value)))
    relative = []
    if re.search(r"\b(?:غدًا|غدا|بكره|بكرة|tomorrow)\b", value, re.I):
        relative.append(now.date() + dt.timedelta(days=1))
    if re.search(r"\b(?:اليوم|today)\b", value, re.I):
        relative.append(now.date())

    dates = []
    for raw in iso_dates:
        try:
            dates.append(dt.date.fromisoformat(raw))
        except ValueError as exc:
            raise ValueError("NEEDS_INPUT: تاريخ الموعد النهائي غير صالح.") from exc
    dates.extend(relative)
    dates = list(dict.fromkeys(dates))
    if len(dates) != 1:
        if len(dates) > 1:
            raise ValueError("NEEDS_INPUT: وجدت أكثر من تاريخ للموعد النهائي؛ حدد تاريخًا واحدًا.")
        raise ValueError("NEEDS_INPUT: حدد تاريخ الموعد النهائي بصيغة YYYY-MM-DD أو اليوم/غدًا.")

    clock = _parse_clock(value)
    if clock is None:
        raise ValueError("NEEDS_INPUT: حدد وقت الموعد النهائي، مثال: الساعة 10:00 صباحًا.")
    deadline = dt.datetime.combine(dates[0], dt.time(clock[0], clock[1]), TZ)
    if deadline <= now:
        raise ValueError("NEEDS_INPUT: الموعد النهائي يجب أن يكون في المستقبل.")
    return deadline


def _parse_reminder_minutes(text: str, *, deadline_present: bool) -> int | None:
    value = (text or "").translate(_AR_DIGITS)
    requested = bool(re.search(r"ذكرني|ذكّرني|تذكير|remind", value, re.I))
    if not requested:
        return None
    if not deadline_present:
        raise ValueError("NEEDS_INPUT: لا أستطيع إنشاء تذكير بدون موعد نهائي واضح.")
    if re.search(r"قبل\s+ساعتين", value):
        return 120
    if re.search(r"قبل\s+(?:ساعة|ساعه)", value):
        return 60
    if re.search(r"قبل\s+نصف\s+(?:ساعة|ساعه)", value):
        return 30
    match = re.search(r"قبل\s+(\d+)\s*(?:دقيقة|دقيقه|دقائق|minute|minutes)", value, re.I)
    if match:
        return max(0, min(10080, int(match.group(1))))
    match = re.search(r"قبل\s+(\d+)\s*(?:ساعة|ساعه|ساعات|hour|hours)", value, re.I)
    if match:
        return max(0, min(10080, int(match.group(1)) * 60))
    return 60


def format_deadline(value: dt.datetime | str) -> str:
    if isinstance(value, str):
        parsed = dt.datetime.fromisoformat(value)
    else:
        parsed = value
    parsed = parsed.astimezone(TZ) if parsed.tzinfo else parsed.replace(tzinfo=TZ)
    period = "صباحًا" if parsed.hour < 12 else "مساءً"
    hour12 = parsed.hour % 12 or 12
    return (
        f"{_DAYS_AR[parsed.weekday()]} {parsed.day} {_MONTHS_AR[parsed.month - 1]} {parsed.year}، "
        f"الساعة {hour12}:{parsed.minute:02d} {period}"
    )


def _deadline_sheet_value(deadline: dt.datetime) -> str:
    return deadline.strftime("%Y-%m-%d %H:%M")


def _extended_build_plan(text: str, *, chat_id: int | str = "", message_id: int | str = "") -> dict:
    plan = _ORIGINAL_BUILD_PLAN(text, chat_id=chat_id, message_id=message_id)
    deadline = _parse_deadline(text)
    reminder_minutes = _parse_reminder_minutes(text, deadline_present=deadline is not None)
    if deadline is None:
        return plan

    project = base._find_project(text)
    headers, row = project["headers"], project["row"]
    if "الموعد النهائي" not in headers:
        raise RuntimeError("Projects schema is missing الموعد النهائي")
    col = headers.index("الموعد النهائي") + 1
    plan["mutations"].append({
        "kind": "deadline_cell",
        "sheet": "Projects",
        "cell": f"{base._column_letter(col)}{project['row_no']}",
        "before": base._value(row, headers, "الموعد النهائي"),
        "after": _deadline_sheet_value(deadline),
        "deadline_iso": deadline.isoformat(),
        "deadline_human": format_deadline(deadline),
        "label": f"{project['project_id']} الموعد النهائي",
    })
    if reminder_minutes is not None:
        plan["mutations"].append({
            "kind": "calendar_deadline_reminder",
            "project_id": project["project_id"],
            "project_name": project["name"],
            "deadline_iso": deadline.isoformat(),
            "reminder_minutes": reminder_minutes,
        })
    plan["version"] = "natural-action/1.1"
    return plan


def _extended_create_preview(text: str, *, chat_id: int | str = "", message_id: int | str = "") -> dict:
    # Reuse base's audited preview mechanism while temporarily presenting the
    # extended plan through its public build_plan reference.
    original = base.build_plan
    try:
        base.build_plan = _extended_build_plan
        return _ORIGINAL_CREATE_PREVIEW(text, chat_id=chat_id, message_id=message_id)
    finally:
        base.build_plan = original


def _extended_render_preview(record: dict) -> str:
    plan = record["plan"]
    lines = [
        "🧾 ACTION PREVIEW",
        f"المشروع: {plan['project']['project_id']} — {plan['project']['name']}",
    ]
    n = 0
    for item in plan["mutations"]:
        n += 1
        if item["kind"] == "sheet_cell":
            lines.append(f"{n}. {item['label']}: {item['before'] or 'غير محدد'} → {item['after']}")
        elif item["kind"] == "waiting_append":
            lines.append(f"{n}. انتظار: رد/موافقة من {item['person']}")
        elif item["kind"] == "durable_fact":
            lines.append(f"{n}. ذاكرة دائمة: {item['value']}")
        elif item["kind"] == "deadline_cell":
            lines.append(f"{n}. الموعد النهائي: {item['deadline_human']}")
        elif item["kind"] == "calendar_deadline_reminder":
            minutes = int(item["reminder_minutes"])
            lead = "ساعة" if minutes == 60 else ("ساعتين" if minutes == 120 else f"{minutes} دقيقة")
            lines.append(f"{n}. التذكير: قبل الموعد بـ {lead}")
    lines += [
        "",
        "لم يتم تنفيذ أي تغيير بعد.",
        f"للموافقة والتنفيذ: /approve_action {record['action_id']} {record['approval_code']}",
        f"للرفض: /reject_action {record['action_id']}",
    ]
    return "\n".join(lines)


def _extended_execute(action_id: str, approval_code: str) -> dict:
    action = base._claim(action_id, approval_code)
    plan = action["plan"]
    receipts, errors = [], []
    project_id = plan["project"]["project_id"]

    for item in plan["mutations"]:
        try:
            if item["kind"] == "sheet_cell":
                header = "نسبة الإنجاز" if "نسبة الإنجاز" in item["label"] else "الخطوة التالية"
                current, fresh_cell = base._fresh_project_value(project_id, header)
                if fresh_cell != item["cell"] or current != str(item["before"]):
                    raise RuntimeError(
                        f"STALE_PREVIEW {item['sheet']}!{item['cell']}: expected {item['before']!r}, current {current!r}"
                    )
                receipt = sheets.update_cell(item["sheet"], item["cell"], item["after"])
                receipts.append({"kind": "sheet_cell", "destination": f"{item['sheet']}!{item['cell']}",
                                 "before": item["before"], "after": item["after"], "provider_receipt": receipt})
            elif item["kind"] == "waiting_append":
                receipts.append(base._append_waiting(item))
            elif item["kind"] == "durable_fact":
                receipts.append(base._store_fact(item, action_id))
            elif item["kind"] == "deadline_cell":
                current, fresh_cell = base._fresh_project_value(project_id, "الموعد النهائي")
                if fresh_cell != item["cell"] or current != str(item["before"]):
                    raise RuntimeError(
                        f"STALE_PREVIEW {item['sheet']}!{item['cell']}: expected {item['before']!r}, current {current!r}"
                    )
                receipt = sheets.update_cell(item["sheet"], item["cell"], item["after"])
                receipts.append({"kind": "deadline_cell", "destination": f"{item['sheet']}!{item['cell']}",
                                 "before": item["before"], "after": item["after"],
                                 "deadline_human": item["deadline_human"], "provider_receipt": receipt})
            elif item["kind"] == "calendar_deadline_reminder":
                deadline = dt.datetime.fromisoformat(item["deadline_iso"])
                event = calendar_actions.create_event({
                    "title": f"موعد نهائي — {item['project_id']} {item['project_name']}",
                    "start": deadline,
                    "end": deadline + dt.timedelta(minutes=15),
                    "reminder_minutes": int(item["reminder_minutes"]),
                })
                receipts.append({"kind": "calendar_reminder", "id": event.get("id", ""),
                                 "destination": "Google Calendar", "deadline_human": format_deadline(deadline),
                                 "reminder_minutes": int(item["reminder_minutes"]), "provider_receipt": event})
        except Exception as exc:
            errors.append(f"{item['kind']}: {type(exc).__name__}: {str(exc)[:220]}")
            break

    final_status = "EXECUTED" if not errors else ("PARTIAL" if receipts else "FAILED")

    def finalize(state):
        row = next((x for x in state["action_queue"] if x.get("action_id") == action_id), None)
        if not row:
            return False, None
        row["status"] = final_status
        row["executed_at"] = base._now()
        row["receipts"] = receipts
        row["errors"] = errors
        return True, row

    Store().transaction(finalize, "natural_action_finalize", action_id=action_id, status=final_status)
    return {"action_id": action_id, "status": final_status, "receipts": receipts,
            "errors": errors, "project": plan.get("project") or {}}


def project_report(query: str = "") -> str:
    project = base._find_project(query or "المشروع")
    headers, row = project["headers"], project["row"]
    def get(name):
        return base._value(row, headers, name) or "غير محدد"

    waiting_rows = (sheets.snapshot(max_rows=150, max_cols=11).get("Waiting_For") or [])[1:]
    waiting = []
    for row2 in waiting_rows:
        joined = " | ".join(map(str, row2))
        if project["project_id"] in joined and (len(row2) < 9 or str(row2[8]).strip() in {"", "بانتظار", "OPEN", "WAITING"}):
            who = str(row2[2]).strip() if len(row2) > 2 and str(row2[2]).strip() else "NEEDS_INPUT"
            waiting.append(who)

    deadline = get("الموعد النهائي")
    deadline_line = deadline
    try:
        if deadline != "غير محدد":
            raw = deadline.replace(" ", "T", 1) if " " in deadline and "T" not in deadline else deadline
            deadline_line = format_deadline(dt.datetime.fromisoformat(raw).replace(tzinfo=TZ))
    except Exception:
        deadline_line = deadline

    lines = [
        f"📌 تقرير {project['project_id']} — {project['name']}",
        f"الحالة: {get('الحالة')}",
        f"الإنجاز: {get('نسبة الإنجاز')}",
        f"المرحلة: {get('المرحلة الحالية')}",
        f"الخطوة التالية: {get('الخطوة التالية')}",
        f"الموعد النهائي: {deadline_line}",
        f"الانتظار: {', '.join(waiting[:3]) if waiting else 'لا يوجد انتظار مرتبط مؤكد'}",
        f"آخر تحديث: {get('آخر تحديث')}",
    ]
    return "\n".join(lines)


def _extended_render_receipt(result: dict) -> str:
    lines = [f"✅ تم التنفيذ — {result['action_id']}", f"الحالة: {result['status']}"]
    for item in result.get("receipts", []):
        if item["kind"] == "sheet_cell":
            lines.append(f"• تم تحديث {item['destination']}: {item['before'] or 'غير محدد'} → {item['after']}")
        elif item["kind"] == "deadline_cell":
            lines.append(f"• الموعد النهائي: {item['deadline_human']}")
        elif item["kind"] == "calendar_reminder":
            minutes = int(item.get("reminder_minutes", 0))
            lead = "ساعة" if minutes == 60 else ("ساعتين" if minutes == 120 else f"{minutes} دقيقة")
            lines.append(f"• التذكير: تم إنشاؤه في Google Calendar قبل الموعد بـ {lead}")
        else:
            lines.append(f"• {item['kind']}: {item.get('id', '')} → {item.get('destination', '')}")
    if result.get("errors"):
        lines.append("⚠️ لم يكتمل كل التنفيذ: " + " | ".join(result["errors"]))
    project = result.get("project") or {}
    if project.get("project_id"):
        try:
            lines += ["", project_report(project["project_id"])]
        except Exception as exc:
            lines.append(f"⚠️ تعذر تحديث التقرير اللحظي: {type(exc).__name__}")
    return "\n".join(lines)


def report_request(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    if text.lower().startswith("/report"):
        return True, text[len("/report"):].strip()
    match = _REPORT_RE.match(text)
    if not match:
        return False, ""
    return True, (match.group(1) or match.group(2) or "").strip()


def install():
    global _INSTALLED, _ORIGINAL_BUILD_PLAN, _ORIGINAL_CREATE_PREVIEW, _ORIGINAL_RENDER_PREVIEW
    global _ORIGINAL_EXECUTE, _ORIGINAL_RENDER_RECEIPT
    if _INSTALLED:
        return

    _ORIGINAL_BUILD_PLAN = base.build_plan
    _ORIGINAL_CREATE_PREVIEW = base.create_preview
    _ORIGINAL_RENDER_PREVIEW = base.render_preview
    _ORIGINAL_EXECUTE = base.execute
    _ORIGINAL_RENDER_RECEIPT = base.render_receipt

    base.build_plan = _extended_build_plan
    base.create_preview = _extended_create_preview
    base.render_preview = _extended_render_preview
    base.execute = _extended_execute
    base.render_receipt = _extended_render_receipt

    from connectors import telegram_bot_legacy as legacy
    original_handle = legacy.handle_message
    original_start = legacy.command_start
    original_configure = legacy.configure_commands

    def command_start(chat_id: int):
        original_start(chat_id)
        legacy.send(chat_id, "\n📌 التقارير والمواعيد\n/report PRJ-001 — أرسل تقرير المشروع الحالي\nمثال تنفيذ: نفذ تحديث PRJ-001 إلى 50%، الموعد النهائي غدًا الساعة 10:00، ذكرني قبل ساعة")

    def configure_commands():
        original_configure()
        try:
            import json
            commands = legacy.api("getMyCommands") or []
            existing = {str(item.get("command", "")) for item in commands}
            if "report" not in existing:
                commands.append({"command": "report", "description": "تقرير مشروع حي من Sheets"})
            legacy.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:
            print(f"Report command menu warning: {exc}", flush=True)

    def handle_message(message: dict):
        raw = (message.get("text") or message.get("caption") or "").strip()
        is_report, query = report_request(raw)
        if not is_report:
            return original_handle(message)
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        if not legacy._authorized(chat_id, chat.get("type", "")):
            legacy.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
            return
        text, kind, attachment = legacy._message_payload(message)
        iid = legacy._local_capture(text, message, kind)
        try:
            if kind != "TEXT":
                raise ValueError("استخدم طلب التقرير كنص أو بعد تفريغ الصوت.")
            answer = project_report(query or "المشروع")
            legacy.send(chat_id, answer)
            legacy._save_intake(iid, message, text, kind, attachment, "COMPLETED")
        except Exception as exc:
            legacy.send(chat_id, "❌ " + str(exc)[:1200])
            legacy._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)

    legacy.handle_message = handle_message
    legacy.command_start = command_start
    legacy.configure_commands = configure_commands
    _INSTALLED = True

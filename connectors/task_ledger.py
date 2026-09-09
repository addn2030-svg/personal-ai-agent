# -*- coding: utf-8 -*-
"""Task Ledger upsert — bulk task matrix into «خطة الإنجاز والمهام».

Closes the operational gap from the 2026-09-09 Life & Work OS session: a
prepared task matrix (Task_ID / Title / Domain / Owner / Due_Date / Status /
Next_Action) must land in the live task sheet through the repo's standard
governance — preview -> explicit approval -> execution -> receipts — instead
of manual cell edits.

Schema-adaptive by design (the live tab's exact headers are not hardcoded):
- fields are located by header aliases (المهمة/Title، المسؤول/Owner، ...) so
  column-order changes cannot corrupt data;
- missing canonical columns are added as previewed header-row mutations;
- updates re-verify the captured before-value at execution time (STALE_PREVIEW
  guard, same policy as the Natural Action Executor);
- appended rows are re-checked for duplicates immediately before the write.

Telegram surface (installed by install()):
- /tasks_import <JSON matrix>  -> normalized plan + preview + approval token
- /confirm_tasks <token>       -> execution + receipts + honest status log
- /tasks                       -> read-only ledger listing grouped by life domain
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import time

from connectors import life_domains
from connectors import sheet_intelligence as sheets
from connectors.sheet_intelligence import _column_letter

LEDGER_TAB = os.environ.get("TASK_LEDGER_SHEET", "خطة الإنجاز والمهام").strip()
MAX_IMPORT_TASKS = 20
IMPORT_WINDOW_SECONDS = 900
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FIELD_ALIASES = {
    "task_id": ("Task_ID", "Task ID", "المعرف", "رقم المهمة"),
    "title": ("Title", "المهمة", "عنوان المهمة", "البند", "النشاط"),
    "domain": ("Domain", "الدائرة", "المجال", "القطاع"),
    "owner": ("Owner", "المسؤول", "المالك", "المكلف"),
    "due_date": ("Due_Date", "Due Date", "الموعد النهائي", "تاريخ الاستحقاق", "الاستحقاق", "التاريخ المستهدف"),
    "status": ("Status", "الحالة"),
    "next_action": ("Next_Action", "Next Action", "الخطوة التالية", "الإجراء التالي"),
}
CANONICAL_FIELDS = ("task_id", "title", "domain", "owner", "due_date", "status", "next_action")
REQUIRED_FIELDS = ("task_id", "title")
# Header used when a canonical column must be created (each is its own alias,
# so a re-read after creation maps the field back).
DEFAULT_HEADERS = {
    "task_id": "Task_ID",
    "title": "المهمة",
    "domain": "الدائرة",
    "owner": "المسؤول",
    "due_date": "الموعد النهائي",
    "status": "الحالة",
    "next_action": "الخطوة التالية",
}

bot = None  # bound by install(); the live telegram bot module.
_PENDING_IMPORTS: dict[str, dict] = {}


def _safe_error(exc: Exception) -> str:
    try:
        from connectors.model_gateway import _safe_error as model_safe_error

        return model_safe_error(exc)
    except Exception:
        return str(exc).replace("\n", " ")[:240]


# ---------------------------------------------------------------------------
# Matrix normalization
# ---------------------------------------------------------------------------

def _key_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in CANONICAL_FIELDS:
        for alias in (field, *FIELD_ALIASES[field]):
            mapping[re.sub(r"\s+", " ", alias.lower())] = field
    return mapping


def normalize_matrix(raw) -> list[dict]:
    """Parse and validate a task matrix (JSON text, list, or {'tasks': [...]})."""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("أرسل مصفوفة المهام بصيغة JSON بعد الأمر مباشرة.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("JSON غير صالح: " + str(exc)[:160]) from exc
    else:
        payload = raw
    if isinstance(payload, dict):
        payload = payload.get("tasks") or payload.get("data") or payload.get("matrix")
    if not isinstance(payload, list) or not payload:
        raise ValueError("المصفوفة يجب أن تكون قائمة مهام JSON غير فارغة.")

    key_map = _key_map()
    seen: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("كل مهمة يجب أن تكون كائن JSON.")
        clean = {field: "" for field in CANONICAL_FIELDS}
        for key, value in item.items():
            field = key_map.get(re.sub(r"\s+", " ", str(key).strip().lower()))
            if field:
                clean[field] = str(value or "").strip()
        for field in REQUIRED_FIELDS:
            if not clean[field]:
                raise ValueError("كل مهمة تحتاج Task_ID وTitle على الأقل.")
        if _ISO_DATE.match(clean["due_date"]):
            try:
                dt.date.fromisoformat(clean["due_date"])
            except ValueError as exc:
                raise ValueError(
                    f"تاريخ غير صالح للمهمة {clean['task_id']}: {clean['due_date']} (YYYY-MM-DD)"
                ) from exc
        seen[clean["task_id"]] = clean  # last occurrence wins (de-duplication)
    tasks = list(seen.values())
    if len(tasks) > MAX_IMPORT_TASKS:
        raise ValueError(f"الحد الأقصى {MAX_IMPORT_TASKS} مهمة في الدفعة الواحدة.")
    return tasks


# ---------------------------------------------------------------------------
# Ledger reading and column mapping
# ---------------------------------------------------------------------------

def _grid_columns() -> int:
    try:
        for row in sheets.metadata():
            if str(row.get("title", "")) == LEDGER_TAB:
                return max(1, int(row.get("columns") or 26))
    except Exception:  # noqa: BLE001 - grid check is advisory
        pass
    return 26


def _ledger_rows(data=None) -> list[list]:
    """Rows of the ledger tab; [] for an existing-but-empty tab; ValueError if absent."""
    data = data if data is not None else sheets.snapshot(max_rows=150, max_cols=20)
    rows = (data or {}).get(LEDGER_TAB)
    if rows:
        return rows
    titles = {str(row.get("title", "")) for row in sheets.metadata()}
    if LEDGER_TAB in titles:
        return []  # tab exists but is empty: import may create headers from scratch
    raise ValueError(f"تبويب «{LEDGER_TAB}» غير موجود في الشيت. أنشئه أولًا عبر /newtab.")


def _header_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized = [re.sub(r"\s+", " ", str(h or "").strip()).lower() for h in headers]
    for field, aliases in FIELD_ALIASES.items():
        for index, header in enumerate(normalized):
            if not header:
                continue
            for alias in aliases:
                cleaned = re.sub(r"\s+", " ", alias.lower())
                if header == cleaned or cleaned in header:
                    mapping[field] = index
                    break
            if field in mapping:
                break
    return mapping


def _cell_at(rows: list[list], row_no: int, col: int) -> str:
    """Sheet-row access (row 1 = headers). Tolerates ragged rows."""
    if row_no < 1 or row_no > len(rows):
        return ""
    row = rows[row_no - 1]
    return str(row[col]).strip() if col < len(row) else ""


def _task_row_index(rows: list[list], mapping: dict[str, int]) -> dict[str, int]:
    index: dict[str, int] = {}
    id_col = mapping.get("task_id")
    if id_col is None:
        return index
    for row_no in range(2, len(rows) + 1):
        value = _cell_at(rows, row_no, id_col)
        if value and value not in index:
            index[value] = row_no
    return index


# ---------------------------------------------------------------------------
# Plan (preview) + execute (receipts)
# ---------------------------------------------------------------------------

def plan_upsert(tasks: list[dict], data=None) -> dict:
    """Build the upsert plan: header additions, appends, updates, skips.

    Accepts either canonical task dicts or the raw JSON matrix (normalized
    defensively first), so callers can never bypass validation.
    """
    tasks = normalize_matrix(tasks)
    rows = _ledger_rows(data)
    headers = [str(x or "").strip() for x in (rows[0] if rows else [])]
    mapping = _header_map(headers)
    grid_cols = _grid_columns()

    header_adds: list[dict] = []
    used_cols = len(headers)
    for field in CANONICAL_FIELDS:
        if field in mapping:
            continue
        if not any(task.get(field) for task in tasks):
            continue  # column only created when at least one task carries the field
        if used_cols + 1 > grid_cols:
            raise ValueError(
                f"لا يمكن إضافة عمود «{DEFAULT_HEADERS[field]}»: حد أعمدة التبويب {grid_cols}."
            )
        used_cols += 1
        mapping[field] = used_cols - 1
        header_adds.append({
            "field": field,
            "header": DEFAULT_HEADERS[field],
            "cell": f"{_column_letter(used_cols)}1",
        })

    effective_headers = list(headers) + [""] * (used_cols - len(headers))
    for add in header_adds:
        effective_headers[mapping[add["field"]]] = add["header"]

    index = _task_row_index(rows, mapping)
    mutations: list[dict] = []
    skipped: list[dict] = []
    for task in tasks:
        row_no = index.get(task["task_id"])
        if row_no is None:
            values = [""] * len(effective_headers)
            for field, col in mapping.items():
                if task.get(field):
                    values[col] = task[field]
            mutations.append({
                "task_id": task["task_id"], "kind": "append_row",
                "title": task["title"], "values": values,
            })
            continue
        writes: list[dict] = []
        for field in CANONICAL_FIELDS:
            col = mapping.get(field)
            if col is None or not task.get(field):
                continue
            before = _cell_at(rows, row_no, col)
            if before == task[field]:
                continue
            writes.append({
                "a1": f"{_column_letter(col + 1)}{row_no}",
                "col": col,
                "row_no": row_no,
                "header": effective_headers[col] or DEFAULT_HEADERS[field],
                "before": before,
                "after": task[field],
            })
        if not writes:
            skipped.append({"task_id": task["task_id"], "reason": "البيانات مطابقة — لا تغييرات"})
            continue
        mutations.append({
            "task_id": task["task_id"], "kind": "update_row",
            "title": task["title"], "row_no": row_no, "writes": writes,
        })

    warnings: list[str] = []
    if any(m["kind"] == "append_row" for m in mutations) and not _direct_route_ready():
        warnings.append(
            "الإضافات تتطلب مسار Service Account المباشر؛ بوابة Apps Script قد ترفض التبويبات غير المدرجة."
        )
    return {
        "tab": LEDGER_TAB,
        "headers": effective_headers,
        "header_adds": header_adds,
        "mutations": mutations,
        "skipped": skipped,
        "warnings": warnings,
        "planned_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def _direct_route_ready() -> bool:
    try:
        return bool(sheets._direct_ready())
    except Exception:  # noqa: BLE001
        return False


def _align_row(values: list[str], width: int) -> list[str]:
    row = [str(v or "") for v in values]
    if len(row) >= width:
        return row[:width]
    return row + [""] * (width - len(row))


def execute_plan(plan: dict) -> dict:
    """Execute an approved plan with staleness guards; partial failures allowed."""
    rows = _ledger_rows()
    headers = [str(x or "").strip() for x in (rows[0] if rows else [])]

    # 1) Header additions (idempotent: an already-applied header is skipped).
    for add in plan.get("header_adds", []):
        match = re.fullmatch(r"([A-Z]{1,3})(\d+)", add["cell"])
        if not match:
            raise RuntimeError(f"عنوان خلية غير صالح: {add['cell']}")
        col = _column_number(match.group(1)) - 1
        current = _cell_at(rows, 1, col)
        if current == add["header"]:
            continue
        if current:
            raise RuntimeError(
                f"STALE_PREVIEW {add['cell']}: تحتوي «{current}» بدل عمود فارغ"
            )
        sheets.update_cell(plan["tab"], add["cell"], add["header"])
        if len(headers) <= col:
            headers.extend([""] * (col + 1 - len(headers)))
        headers[col] = add["header"]

    # 2) Fresh task index for duplicate guards.
    fresh_mapping = _header_map(headers)
    fresh_index = _task_row_index(rows, fresh_mapping)
    width = max(len(headers), len(plan.get("headers") or []))

    receipts: list[dict] = []
    errors: list[dict] = []
    appended = 0
    for mutation in plan.get("mutations", []):
        try:
            if mutation["kind"] == "update_row":
                for write in mutation["writes"]:
                    current = _cell_at(rows, write["row_no"], write["col"])
                    if current != write["before"]:
                        raise RuntimeError(
                            f"STALE_PREVIEW {write['a1']}: متوقع «{write['before']}»، الحالي «{current}»"
                        )
                for write in mutation["writes"]:
                    provider_receipt = sheets.update_cell(plan["tab"], write["a1"], write["after"])
                    receipts.append({
                        "task_id": mutation["task_id"], "kind": "cell",
                        "destination": f"{plan['tab']}!{write['a1']}",
                        "header": write["header"],
                        "before": write["before"], "after": write["after"],
                        "provider_receipt": provider_receipt,
                    })
            else:  # append_row
                if mutation["task_id"] in fresh_index:
                    raise RuntimeError(
                        f"DUPLICATE {mutation['task_id']}: المهمة موجودة مسبقًا في السجل"
                    )
                row = _align_row(mutation["values"], width)
                provider_receipt = sheets.append_row(plan["tab"], row)
                appended += 1
                receipts.append({
                    "task_id": mutation["task_id"], "kind": "row",
                    "destination": plan["tab"],
                    "preview": " | ".join(v for v in row if v)[:160],
                    "provider_receipt": provider_receipt,
                })
        except Exception as exc:  # noqa: BLE001 - per-task failure boundary
            errors.append({"task_id": mutation["task_id"], "error": str(exc)[:220]})

    if errors and receipts:
        status = "PARTIAL"
    elif errors:
        status = "FAILED"
    else:
        status = "EXECUTED"
    return {"status": status, "receipts": receipts, "errors": errors, "appended": appended}


def _column_number(letters: str) -> int:
    number = 0
    for char in letters.upper():
        number = number * 26 + (ord(char) - 64)
    return number


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_plan_preview(plan: dict, token: str) -> str:
    appends = sum(1 for m in plan["mutations"] if m["kind"] == "append_row")
    updates = sum(1 for m in plan["mutations"] if m["kind"] == "update_row")
    lines = [
        f"📥 معاينة تحديث سجل المهام — {plan['tab']}",
        f"الإحصاء: إضافة {appends} · تحديث {updates} · تخطي {len(plan['skipped'])}",
        "لم يُنفذ أي تغيير بعد.",
        "",
    ]
    for add in plan["header_adds"]:
        lines.append(f"➕ عمود جديد: «{add['header']}» في {add['cell']}")
    for mutation in plan["mutations"]:
        if mutation["kind"] == "append_row":
            preview = " | ".join(v for v in mutation["values"] if v)[:160]
            lines.append(f"🆕 {mutation['task_id']} — صف جديد: {preview}")
        else:
            parts = [
                f"{w['header']}: {w['before'] or '∅'} → {w['after']}"
                for w in mutation["writes"]
            ]
            lines.append(
                f"✏️ {mutation['task_id']} — تحديث صف {mutation['row_no']}: "
                + "؛ ".join(parts)[:320]
            )
    for skip in plan["skipped"]:
        lines.append(f"⏭️ {skip['task_id']} — {skip['reason']}")
    if not plan["mutations"] and not plan["header_adds"]:
        lines.append("• لا توجد تغييرات مطلوبة.")
    for warning in plan["warnings"]:
        lines.append("⚠️ " + warning)
    lines += ["", f"للاعتماد خلال 15 دقيقة:\n/confirm_tasks {token}"]
    return "\n".join(lines)[:3500]


def render_execution_report(result: dict) -> str:
    status_label = {"EXECUTED": "✅", "PARTIAL": "⚠️", "FAILED": "❌"}.get(result["status"], "•")
    lines = [
        f"{status_label} تنفيذ تحديث سجل المهام — {result['status']}",
        f"نجح: {len(result['receipts'])} عملية · فشل: {len(result['errors'])}",
        "",
    ]
    for receipt in result["receipts"][:12]:
        if receipt["kind"] == "cell":
            lines.append(
                f"• {receipt['task_id']}: {receipt['header']} — "
                f"{receipt['before'] or '∅'} → {receipt['after']} ({receipt['destination']})"
            )
        else:
            lines.append(f"• {receipt['task_id']}: صف جديد في {receipt['destination']}")
    for error in result["errors"][:6]:
        lines.append(f"⚠️ {error['task_id']}: {error['error']}")
    if len(result["receipts"]) > 12:
        lines.append(f"• ...و{len(result['receipts']) - 12} عملية أخرى")
    return "\n".join(lines)[:3500]


def render_tasks_text() -> str:
    """Read-only ledger listing grouped by life domain, with overdue markers."""
    rows = _ledger_rows()
    headers = [str(x or "").strip() for x in (rows[0] if rows else [])]
    mapping = _header_map(headers)
    if "task_id" not in mapping and "title" not in mapping:
        return (
            f"⚠️ لم أتعرف على أعمدة السجل في «{LEDGER_TAB}».\n"
            "تأكد من وجود عمودي Task_ID و«المهمة»، أو استخدم /tasks_import لإنشائهما."
        )

    def value(row_no: int, field: str) -> str:
        col = mapping.get(field)
        return _cell_at(rows, row_no, col) if col is not None else ""

    today = dt.date.today()
    items: list[dict] = []
    for row_no in range(2, len(rows) + 1):
        if not any(_cell_at(rows, row_no, c) for c in range(len(headers))):
            continue
        due = value(row_no, "due_date")
        overdue = bool(_ISO_DATE.match(due) and dt.date.fromisoformat(due) < today)
        items.append({
            "task_id": value(row_no, "task_id"),
            "title": value(row_no, "title") or "(بدون عنوان)",
            "status": value(row_no, "status"),
            "due": due,
            "domain": value(row_no, "domain"),
            "row": row_no,
            "overdue": overdue,
        })

    groups: dict[str, list[dict]] = {}
    for item in items:
        key = life_domains.label_to_key(item["domain"]) or life_domains.classify_text(
            f"{item['task_id']} {item['title']}"
        )
        groups.setdefault(key or "_other", []).append(item)

    lines = [f"📋 سجل المهام — {LEDGER_TAB} ({len(items)} مهمة)"]
    ordered_keys = sorted(groups, key=lambda k: (life_domains.domain_order(None if k == "_other" else k), k))
    for key in ordered_keys:
        group = groups[key]
        badge = life_domains.badge(None if key == "_other" else key)
        lines.append(f"\n{badge} ({len(group)})")
        for item in group[:8]:
            markers = ""
            if item["overdue"]:
                markers += " ⏰"
            if item["status"]:
                markers += f" [{item['status']}]"
            due = f" — {item['due']}" if item["due"] else ""
            label = item["task_id"] or f"صف {item['row']}"
            lines.append(f"• {label}: {item['title'][:80]}{due}{markers}")
        if len(group) > 8:
            lines.append(f"• ...و{len(group) - 8} مهمة أخرى")
    if not items:
        lines.append("• السجل فارغ حاليًا.")
    return "\n".join(lines)[:3500]


# ---------------------------------------------------------------------------
# Telegram commands + installation
# ---------------------------------------------------------------------------

_USAGE = (
    "الاستخدام:\n/tasks_import ["
    '{"Task_ID": "TASK-0001", "Title": "المهمة", "Domain": "الدائرة", '
    '"Owner": "المسؤول", "Due_Date": "2026-09-30", "Status": "PENDING", '
    '"Next_Action": "الخطوة التالية"}'
    "]\nيقبل أيضًا {\"tasks\": [...]} — الحد 20 مهمة."
)


def command_tasks_import(chat_id: int, raw: str):
    try:
        tasks = normalize_matrix(raw)
    except ValueError as exc:
        bot.send(chat_id, "❌ " + str(exc)[:400] + "\n\n" + _USAGE)
        return
    try:
        plan = plan_upsert(tasks)
    except Exception as exc:  # noqa: BLE001 - planning boundary
        bot.send(chat_id, "❌ تعذر تجهيز خطة التحديث: " + _safe_error(exc)[:300])
        return
    token = secrets.token_hex(3)
    _PENDING_IMPORTS[token] = {
        "chat_id": str(chat_id),
        "plan": plan,
        "tasks": tasks,
        "expires": time.time() + IMPORT_WINDOW_SECONDS,
    }
    bot.send(chat_id, render_plan_preview(plan, token))


def command_confirm_tasks(chat_id: int, token: str):
    token = (token or "").strip()
    item = _PENDING_IMPORTS.get(token)
    if not item:
        bot.send(chat_id, "❌ رمز اعتماد تحديث المهام غير صالح.")
        return
    if item.get("expires", 0) < time.time():
        _PENDING_IMPORTS.pop(token, None)
        bot.send(chat_id, "❌ انتهت مدة رمز الاعتماد (15 دقيقة). ابدأ بـ /tasks_import من جديد.")
        return
    if item.get("chat_id") != str(chat_id):
        bot.send(chat_id, "❌ هذا الرمز لا يخص هذه المحادثة.")
        return
    _PENDING_IMPORTS.pop(token, None)
    try:
        result = execute_plan(item["plan"])
    except Exception as exc:  # noqa: BLE001 - execution boundary
        safe = _safe_error(exc)
        bot.send(chat_id, "❌ فشل تنفيذ التحديث قبل أي كتابة: " + safe[:300])
        return
    summary = (
        f"{result['status']} | عمليات: {len(result['receipts'])} | أخطاء: {len(result['errors'])}"
    )
    logged = False
    try:
        bot._append(bot.STATUS_TAB, [
            bot._now(), "TASK_LEDGER_IMPORT", result["status"], summary,
            "v1.0", bot.AWS_REGION, bot.BEDROCK_MODEL_ID, bot._now(),
        ])
        logged = True
    except Exception as exc:  # noqa: BLE001 - Sheets boundary
        print(f"Task ledger status log error: {_safe_error(exc)}", flush=True)
    report = render_execution_report(result)
    if logged:
        report += f"\n\n💾 إيصال التوثيق: {bot.STATUS_TAB} — TASK_LEDGER_IMPORT · {result['status']}"
    else:
        report += "\n\n⚠️ نُفذ التحديث لكن تعذر توثيقه في Google Sheets الآن."
    bot.send(chat_id, report)


def command_tasks(chat_id: int):
    try:
        bot.send(chat_id, render_tasks_text())
    except Exception as exc:  # noqa: BLE001 - read boundary
        bot.send(chat_id, "❌ تعذر قراءة سجل المهام: " + _safe_error(exc)[:300])


def _run_chat_command(chat: dict, message: dict, action, status: str = "COMPLETED"):
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
        bot.send(chat_id, "❌ تعذر تنفيذ الطلب: " + safe[:220])
        bot._save_intake(iid, message, text, kind, attachment, "ERROR", error=safe)


def install(bot_module):
    """Attach the Task Ledger commands to the live bot module (idempotent)."""
    global bot
    bot = bot_module
    if getattr(bot_module, "_task_ledger_installed", False):
        return bot_module

    original_handle = bot_module.handle_message
    original_configure = bot_module.configure_commands

    def handle_message(message: dict):
        raw = (message.get("text") or message.get("caption") or "").strip()
        command = raw.split()[0].split("@")[0].lower() if raw else ""
        chat = message.get("chat") or {}
        if command == "/tasks_import":
            payload = raw[len(command):].strip()
            return _run_chat_command(chat, message, lambda cid: command_tasks_import(cid, payload))
        if command == "/confirm_tasks":
            token = raw[len(command):].strip()
            return _run_chat_command(
                chat, message, lambda cid: command_confirm_tasks(cid, token), status="REVIEW_REQUIRED"
            )
        if command == "/tasks":
            return _run_chat_command(chat, message, command_tasks)
        return original_handle(message)

    def configure_commands():
        original_configure()
        try:
            commands = bot_module.api("getMyCommands") or []
            existing = {str(item.get("command", "")) for item in commands}
            additions = [
                {"command": "tasks", "description": "سجل المهام مجمّعًا حسب الدوائر الحيوية"},
                {"command": "tasks_import", "description": "استيراد مصفوفة مهام JSON بمعاينة واعتماد"},
            ]
            commands.extend(item for item in additions if item["command"] not in existing)
            bot_module.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:  # noqa: BLE001 - menu registration is cosmetic
            print(f"Task ledger command menu warning: {_safe_error(exc)}", flush=True)

    bot_module.handle_message = handle_message
    bot_module.configure_commands = configure_commands
    bot_module.command_tasks = command_tasks
    bot_module.command_tasks_import = command_tasks_import
    bot_module.command_confirm_tasks = command_confirm_tasks
    bot_module._task_ledger_installed = True
    return bot_module

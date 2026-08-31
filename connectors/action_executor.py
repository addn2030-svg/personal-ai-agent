# -*- coding: utf-8 -*-
"""Natural Action Executor v1.

Turns bounded natural-language operational requests into a deterministic preview,
requires explicit approval, then executes supported Sheet/StateStore mutations and
returns receipts. It never lets the model invent a cell, date, owner, or success.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets

from connectors import sheet_intelligence as sheets
from engine.store import Store

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ACTION_PREFIXES = ("نفذ ", "نفّذ ", "manager execute ", "execute ")


def _now() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")


def _today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date().isoformat()


def _as_iso(value) -> str:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value or "")


def _column_letter(index_1_based: int) -> str:
    out = ""
    n = int(index_1_based)
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _projects_table():
    data = sheets.snapshot(max_rows=120, max_cols=15).get("Projects") or []
    if not data:
        raise RuntimeError("Projects sheet is unavailable or empty")
    headers = [str(x).strip() for x in data[0]]
    rows = data[1:]
    return headers, rows


def _find_project(text: str) -> dict:
    headers, rows = _projects_table()
    if "Project_ID" not in headers or "اسم المشروع" not in headers:
        raise RuntimeError("Projects schema is missing Project_ID/اسم المشروع")
    id_col = headers.index("Project_ID")
    name_col = headers.index("اسم المشروع")
    normalized = (text or "").lower()
    explicit = re.search(r"\bPRJ-\d+\b", text or "", re.I)
    matches = []
    for offset, row in enumerate(rows, start=2):
        pid = str(row[id_col]).strip() if id_col < len(row) else ""
        name = str(row[name_col]).strip() if name_col < len(row) else ""
        if not pid:
            continue
        if explicit and pid.lower() == explicit.group(0).lower():
            matches.append((offset, row, pid, name))
        elif name and name.lower() in normalized:
            matches.append((offset, row, pid, name))
    if not matches:
        nonempty = []
        for offset, row in enumerate(rows, start=2):
            pid = str(row[id_col]).strip() if id_col < len(row) else ""
            name = str(row[name_col]).strip() if name_col < len(row) else ""
            if pid:
                nonempty.append((offset, row, pid, name))
        generic = bool(re.search(r"\bproject\b|المشروع|الوكيل|agent", normalized, re.I))
        if generic and len(nonempty) == 1:
            matches = nonempty
    if len(matches) != 1:
        raise ValueError("NEEDS_INPUT: حدد Project_ID أو اسم المشروع بدقة.")
    row_no, row, pid, name = matches[0]
    return {"headers": headers, "row": row, "row_no": row_no, "project_id": pid, "name": name}


def _parse_progress(text: str):
    normalized = (text or "").translate(_AR_DIGITS)
    match = re.search(r"(?<!\d)(\d{1,3})\s*%", normalized)
    if not match:
        return None
    value = int(match.group(1))
    if not 0 <= value <= 100:
        raise ValueError("نسبة الإنجاز يجب أن تكون بين 0% و100%.")
    return f"{value}%"


def _parse_next_action(text: str):
    match = re.search(
        r"(?:الخطوة\s+التالية|next\s+action)\s*(?:هي|=|:)?\s*(.+?)(?=\s+(?:و?أنتظر|و?انتظر|و?بانتظار|و?احفظ|و?تذكر)|[،;\n]|$)",
        text or "", re.I,
    )
    return match.group(1).strip() if match else None


def _parse_waiting(text: str):
    match = re.search(
        r"(?:أنتظر|انتظر|بانتظار|waiting\s+for)\s+(?:رد\s+)?(.+?)(?=\s+(?:و?احفظ|و?تذكر|and\s+remember)|[،,.;\n]|$)",
        text or "", re.I,
    )
    if not match:
        return None
    person = match.group(1).strip(" .،,")
    person = re.sub(r"^رد\s+", "", person).strip()
    return person or None


def _parse_memory(text: str):
    match = re.search(r"(?:احفظ|تذكر|remember)(?:\s+(?:أن|ان|that))?\s+(.+)$", text or "", re.I)
    return match.group(1).strip(" .،,") if match else None


def _value(row, headers, header):
    if header not in headers:
        return ""
    idx = headers.index(header)
    return str(row[idx]).strip() if idx < len(row) else ""


def build_plan(text: str, *, chat_id: int | str = "", message_id: int | str = "") -> dict:
    project = _find_project(text)
    headers, row = project["headers"], project["row"]
    progress = _parse_progress(text)
    next_action = _parse_next_action(text)
    waiting_for = _parse_waiting(text)
    memory_fact = _parse_memory(text)
    mutations = []

    if progress is not None:
        if "نسبة الإنجاز" not in headers:
            raise RuntimeError("Projects schema is missing نسبة الإنجاز")
        col = headers.index("نسبة الإنجاز") + 1
        mutations.append({
            "kind": "sheet_cell",
            "sheet": "Projects",
            "cell": f"{_column_letter(col)}{project['row_no']}",
            "before": _value(row, headers, "نسبة الإنجاز"),
            "after": progress,
            "label": f"{project['project_id']} نسبة الإنجاز",
        })

    if next_action:
        if "الخطوة التالية" not in headers:
            raise RuntimeError("Projects schema is missing الخطوة التالية")
        col = headers.index("الخطوة التالية") + 1
        mutations.append({
            "kind": "sheet_cell",
            "sheet": "Projects",
            "cell": f"{_column_letter(col)}{project['row_no']}",
            "before": _value(row, headers, "الخطوة التالية"),
            "after": next_action,
            "label": f"{project['project_id']} الخطوة التالية",
        })

    if waiting_for:
        mutations.append({
            "kind": "waiting_append",
            "project_id": project["project_id"],
            "project_name": project["name"],
            "person": waiting_for,
        })

    if memory_fact:
        mutations.append({
            "kind": "durable_fact",
            "subject": project["project_id"],
            "predicate": "confirmed_project_fact",
            "value": memory_fact,
            "source_ref": f"telegram:{chat_id}:{message_id}",
        })

    if not mutations:
        raise ValueError("NEEDS_INPUT: لم أجد تحديثًا محددًا يمكن معاينته بأمان.")

    return {
        "version": "natural-action/1",
        "source_text": text,
        "project": {"project_id": project["project_id"], "name": project["name"]},
        "mutations": mutations,
    }


def _plan_hash(plan: dict) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_preview(text: str, *, chat_id: int | str = "", message_id: int | str = "") -> dict:
    plan = build_plan(text, chat_id=chat_id, message_id=message_id)
    digest = _plan_hash(plan)
    action_id = "NA-" + secrets.token_hex(4).upper()
    approval_code = digest[:10].upper()
    record = {
        "action_id": action_id,
        "status": "PENDING_APPROVAL",
        "type": "NATURAL_ACTION_PLAN",
        "created_at": _today(),
        "expires_at": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
        "content_hash": digest,
        "content": text[:1200],
        "approval_code": approval_code,
        "plan": plan,
        "receipts": [],
    }

    def add_action(state):
        state["action_queue"].append(record)
        return True, record

    Store().transaction(add_action, "natural_action_preview", action_id=action_id)
    return record


def render_preview(record: dict) -> str:
    plan = record["plan"]
    lines = [
        "🧾 ACTION PREVIEW",
        f"Project: {plan['project']['project_id']} — {plan['project']['name']}",
    ]
    for idx, item in enumerate(plan["mutations"], 1):
        if item["kind"] == "sheet_cell":
            lines.append(f"{idx}. Sheets {item['sheet']}!{item['cell']}: {item['before'] or '∅'} → {item['after']}")
        elif item["kind"] == "waiting_append":
            lines.append(f"{idx}. Waiting_For: بانتظار {item['person']} — مرتبط بـ {item['project_id']}")
        elif item["kind"] == "durable_fact":
            lines.append(f"{idx}. Durable memory: {item['value']}")
    lines += [
        "",
        "لم يتم تنفيذ أي تغيير بعد.",
        f"للموافقة: /approve_action {record['action_id']} {record['approval_code']}",
        f"للرفض: /reject_action {record['action_id']}",
    ]
    return "\n".join(lines)


def _get_action(action_id: str):
    rows = Store().rows_all().get("action_queue", [])
    return next((x for x in rows if x.get("action_id") == action_id), None)


def _claim(action_id: str, approval_code: str) -> dict:
    code = (approval_code or "").strip().upper()

    def claim(state):
        action = next((x for x in state["action_queue"] if x.get("action_id") == action_id), None)
        if not action:
            raise ValueError("لا يوجد Action بهذا المعرّف.")
        if action.get("status") != "PENDING_APPROVAL":
            raise ValueError(f"Action حالته {action.get('status')} وليست PENDING_APPROVAL.")
        if str(action.get("approval_code", "")).upper() != code:
            raise ValueError("رمز الموافقة غير مطابق.")
        if _as_iso(action.get("expires_at")) < _today():
            action["status"] = "EXPIRED"
            return True, action
        action["status"] = "EXECUTING"
        action["approved_at"] = _now()
        return True, action

    result = Store().transaction(claim, "natural_action_claim", action_id=action_id)
    if result.get("status") == "EXPIRED":
        raise ValueError("انتهت صلاحية Action؛ أنشئ Preview جديدًا.")
    return result


def _fresh_project_value(project_id: str, header: str) -> tuple[str, str]:
    headers, rows = _projects_table()
    if "Project_ID" not in headers or header not in headers:
        raise RuntimeError("Projects schema changed")
    id_idx, value_idx = headers.index("Project_ID"), headers.index(header)
    for row_no, row in enumerate(rows, start=2):
        pid = str(row[id_idx]).strip() if id_idx < len(row) else ""
        if pid == project_id:
            value = str(row[value_idx]).strip() if value_idx < len(row) else ""
            return value, f"{_column_letter(value_idx + 1)}{row_no}"
    raise RuntimeError(f"Project disappeared: {project_id}")


def _append_waiting(item: dict) -> dict:
    if not sheets._direct_ready():
        raise RuntimeError("Waiting_For append requires the verified direct Sheets route")
    data = sheets.snapshot(max_rows=150, max_cols=11).get("Waiting_For") or []
    ids = []
    for row in data[1:]:
        if row and re.fullmatch(r"WAIT-(\d+)", str(row[0]).strip(), re.I):
            ids.append(int(re.fullmatch(r"WAIT-(\d+)", str(row[0]).strip(), re.I).group(1)))
    waiting_id = f"WAIT-{(max(ids) + 1 if ids else 1):04d}"
    row = [
        waiting_id,
        f"{item['project_id']} — {item['project_name']}",
        item["person"],
        "رد/موافقة",
        _today(),
        "",
        "",
        "0",
        "بانتظار",
        "",
        "متابعة عند توفر موعد متوقع",
    ]
    response = sheets._service().spreadsheets().values().append(
        spreadsheetId=sheets.SHEET_ID,
        range="'Waiting_For'!A:K",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    updated_range = ((response.get("updates") or {}).get("updatedRange") or "Waiting_For!A:K")
    return {"kind": "waiting_append", "id": waiting_id, "destination": updated_range}


def _store_fact(item: dict, action_id: str) -> dict:
    raw = f"{item['subject']}|{item['predicate']}|{item['value']}|{item['source_ref']}"
    fact_id = "FACT-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10].upper()
    fact = {
        "fact_id": fact_id,
        "subject": item["subject"],
        "predicate": item["predicate"],
        "value": item["value"],
        "source_ref": item["source_ref"],
        "captured_at": _now(),
        "verification_status": "CONFIRMED_BY_USER",
        "confidence": 1.0,
        "action_id": action_id,
    }

    def add_fact(state):
        if any(x.get("fact_id") == fact_id for x in state["fact_registry"]):
            return False, fact
        state["fact_registry"].append(fact)
        return True, fact

    Store().transaction(add_fact, "natural_action_fact", action_id=action_id, fact_id=fact_id)
    return {"kind": "durable_fact", "id": fact_id, "destination": "StateStore.fact_registry"}


def execute(action_id: str, approval_code: str) -> dict:
    action = _claim(action_id, approval_code)
    plan = action["plan"]
    receipts = []
    errors = []
    project_id = plan["project"]["project_id"]

    for item in plan["mutations"]:
        try:
            if item["kind"] == "sheet_cell":
                header = "نسبة الإنجاز" if "نسبة الإنجاز" in item["label"] else "الخطوة التالية"
                current, fresh_cell = _fresh_project_value(project_id, header)
                if fresh_cell != item["cell"] or current != str(item["before"]):
                    raise RuntimeError(
                        f"STALE_PREVIEW {item['sheet']}!{item['cell']}: expected {item['before']!r}, current {current!r}"
                    )
                receipt = sheets.update_cell(item["sheet"], item["cell"], item["after"])
                receipts.append({
                    "kind": "sheet_cell",
                    "destination": f"{item['sheet']}!{item['cell']}",
                    "before": item["before"],
                    "after": item["after"],
                    "provider_receipt": receipt,
                })
            elif item["kind"] == "waiting_append":
                receipts.append(_append_waiting(item))
            elif item["kind"] == "durable_fact":
                receipts.append(_store_fact(item, action_id))
        except Exception as exc:
            errors.append(f"{item['kind']}: {type(exc).__name__}: {str(exc)[:220]}")
            break

    final_status = "EXECUTED" if not errors else ("PARTIAL" if receipts else "FAILED")

    def finalize(state):
        row = next((x for x in state["action_queue"] if x.get("action_id") == action_id), None)
        if not row:
            return False, None
        row["status"] = final_status
        row["executed_at"] = _now()
        row["receipts"] = receipts
        row["errors"] = errors
        return True, row

    Store().transaction(finalize, "natural_action_finalize", action_id=action_id, status=final_status)
    return {"action_id": action_id, "status": final_status, "receipts": receipts, "errors": errors}


def reject(action_id: str) -> dict:
    def reject_fn(state):
        row = next((x for x in state["action_queue"] if x.get("action_id") == action_id), None)
        if not row:
            raise ValueError("لا يوجد Action بهذا المعرّف.")
        if row.get("status") not in {"PENDING_APPROVAL", "EXECUTING"}:
            raise ValueError(f"لا يمكن رفض Action حالته {row.get('status')}.")
        row["status"] = "REJECTED"
        row["rejected_at"] = _now()
        return True, row
    return Store().transaction(reject_fn, "natural_action_reject", action_id=action_id)


def render_receipt(result: dict) -> str:
    lines = [f"✅ ACTION RECEIPT — {result['action_id']}", f"Status: {result['status']}"]
    for item in result.get("receipts", []):
        if item["kind"] == "sheet_cell":
            lines.append(f"• {item['destination']}: {item['before'] or '∅'} → {item['after']}")
        else:
            lines.append(f"• {item['kind']}: {item.get('id', '')} → {item.get('destination', '')}")
    if result.get("errors"):
        lines.append("⚠️ Errors: " + " | ".join(result["errors"]))
    return "\n".join(lines)


def status_text(limit: int = 5) -> str:
    rows = [x for x in Store().rows_all().get("action_queue", []) if x.get("type") == "NATURAL_ACTION_PLAN"]
    rows = rows[-max(1, limit):]
    if not rows:
        return "لا توجد Natural Actions مسجلة بعد."
    lines = ["🛠 Natural Action Executor"]
    for row in reversed(rows):
        lines.append(f"• {row.get('action_id')} — {row.get('status')} — {str(row.get('content',''))[:90]}")
    return "\n".join(lines)


def natural_request(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    lower = text.lower()
    if lower.startswith("مدير نفذ ") or lower.startswith("مدير نفّذ "):
        return True, text.split(" ", 2)[2].strip()
    for prefix in _ACTION_PREFIXES:
        if lower.startswith(prefix):
            return True, text[len(prefix):].strip()
    return False, ""

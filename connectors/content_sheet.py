# -*- coding: utf-8 -*-
"""Google Sheets adapter for the Content Creator workflow.

The workbook remains the operational source of truth.  This adapter discovers
columns from row 3, reads bounded queue rows, and only writes cells owned by the
agent (draft/status/notes).  Buffer publication is still approval-gated by
``content_creator``.
"""
from __future__ import annotations

import os
from typing import Callable

from connectors import google_credentials

DEFAULT_SHEET_ID = "1E57MbTJWKkr8E0J5_pbhZPyBX9XuZvtZ8T0jH4YjWNQ"
SHEET_ID = os.environ.get("CONTENT_SHEET_ID", DEFAULT_SHEET_ID).strip()
QUEUE_TAB = os.environ.get("CONTENT_QUEUE_TAB", "PUBLISH_QUEUE").strip()
BRAND_TAB = "BRAND_SETUP"
HEADER_ROW = 3
MAX_QUEUE_ROWS = 1006
_SERVICE = None


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _SERVICE = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _SERVICE


def _values(a1: str) -> list[list]:
    return _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=a1
    ).execute().get("values", [])


def _headers() -> list[str]:
    rows = _values(f"'{QUEUE_TAB}'!A{HEADER_ROW}:Z{HEADER_ROW}")
    if not rows:
        raise RuntimeError(f"{QUEUE_TAB} header row is empty")
    return [str(x).strip() for x in rows[0]]


def _records() -> list[dict]:
    headers = _headers()
    rows = _values(f"'{QUEUE_TAB}'!A{HEADER_ROW + 1}:Z{MAX_QUEUE_ROWS}")
    return [dict(zip(headers, list(row) + [""] * (len(headers) - len(row)))) for row in rows if row]


def get_queue_item(queue_id: str | None = None) -> dict:
    records = _records()
    if queue_id:
        wanted = queue_id.strip().upper()
        row = next((x for x in records if str(x.get("Queue_ID", "")).upper() == wanted), None)
        if not row:
            raise ValueError("Queue ID not found: " + wanted)
        return row
    row = next((x for x in records if str(x.get("Status", "")).strip().lower() in {"ready", "idea"}), None)
    if not row:
        raise ValueError("No Ready/Idea row found in PUBLISH_QUEUE")
    return row


def _brand_context() -> str:
    rows = _values(f"'{BRAND_TAB}'!A4:B30")
    pairs = [f"{r[0]}={r[1]}" for r in rows if len(r) > 1 and r[0] and r[1]]
    return "\n".join(pairs)[:5000]


def _idea(row: dict) -> str:
    fields = [
        "Post_Title", "Format", "Hook_AR", "Caption_AR", "Caption_EN", "CTA_AR",
        "Hashtags", "Cover_Text", "Music_Direction", "Internal_Notes",
    ]
    details = "\n".join(f"{key}: {row.get(key)}" for key in fields if row.get(key))
    return f"BRAND:\n{_brand_context()}\n\nQUEUE ITEM {row.get('Queue_ID')}:\n{details}"


def _col_letter(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _queue_row_number(queue_id: str) -> tuple[int, dict[str, int]]:
    headers = _headers()
    values = _values(f"'{QUEUE_TAB}'!A{HEADER_ROW + 1}:A{MAX_QUEUE_ROWS}")
    for offset, row in enumerate(values, HEADER_ROW + 1):
        if row and str(row[0]).strip().upper() == queue_id.strip().upper():
            return offset, {name: idx + 1 for idx, name in enumerate(headers)}
    raise ValueError("Queue ID not found: " + queue_id)


def update_queue(queue_id: str, **fields) -> dict:
    row_number, columns = _queue_row_number(queue_id)
    allowed = {"Buffer_Post_Text", "Status", "Internal_Notes"}
    updates = []
    for name, value in fields.items():
        if name not in allowed or name not in columns:
            continue
        col = _col_letter(columns[name])
        updates.append({"range": f"'{QUEUE_TAB}'!{col}{row_number}", "values": [[str(value)[:10000]]]})
    if not updates:
        return {"updated": 0}
    _service().spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    return {"updated": len(updates), "row": row_number}


def create_preview(queue_id: str | None, *, chat_id: int, model_call: Callable[[str, str], str]) -> dict:
    from connectors import content_creator
    item = get_queue_item(queue_id)
    platform = str(item.get("Platform") or content_creator.DEFAULT_PLATFORM).strip().lower()
    if platform == "x":
        platform = "twitter"
    row = content_creator.create_content_preview(
        _idea(item), chat_id=chat_id, model_call=model_call, platform=platform,
        due_at=(f"{item.get('Scheduled_Date')} {item.get('Scheduled_Time_KSA')}".strip() or None),
        image_url=str(item.get("Media_URL") or "").strip() or None,
    )
    queue_id = str(item.get("Queue_ID"))
    def annotate(state):
        target = next(x for x in state.get("action_queue", []) if x.get("action_id") == row["action_id"])
        target["source_sheet_id"] = SHEET_ID
        target["source_queue_id"] = queue_id
        return True, dict(target)
    row = content_creator.Store().transaction(annotate, "content_sheet_linked", action_id=row["action_id"])
    text = row["content"]
    tags = " ".join(row["content_plan"].get("hashtags") or [])
    if tags:
        text += "\n\n" + tags
    update_queue(
        queue_id,
        Buffer_Post_Text=text,
        Status="Draft",
        Internal_Notes=f"Agent preview {row['action_id']} — approval code required before Buffer",
    )
    return row


def sync_result(row: dict, status: str, note: str) -> None:
    queue_id = row.get("source_queue_id")
    if queue_id and row.get("source_sheet_id") == SHEET_ID:
        update_queue(str(queue_id), Status=status, Internal_Notes=note)


def status_text() -> str:
    info = google_credentials.service_account_info() or {}
    email = info.get("client_email", "service account not configured")
    try:
        count = len(_records())
        state = f"connected ✅ — {count} queue rows"
    except Exception as exc:
        state = "not connected — " + str(exc)[:180]
    return "\n".join([
        "📊 Content Sheet", f"Workbook: {SHEET_ID}", f"Queue: {QUEUE_TAB}",
        f"Service account: {email}", f"Status: {state}",
    ])

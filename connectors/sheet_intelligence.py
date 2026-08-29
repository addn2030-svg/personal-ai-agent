# -*- coding: utf-8 -*-
"""Safe Google Sheets read/search/update layer for Telegram intelligence."""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import google_credentials

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
_SERVICE = None
PRIORITY_TABS = [
    "Projects", "خطة الإنجاز والمهام", "Smart_Inbox", "Waiting_For", "Blockers",
    "Executive_Brief", "التطوير الشخصي", "الهدف المالي E-S-B-I",
    "التحليل المالي المختصر", "تعليمات تجاوز نقاط الضعف",
    "المصادر والتعلم العلمي", "القرارات",
]
EXCLUDED_CONTEXT_TABS = {"Calc_Data", "مدخلات الوكيل", "محادثات الوكيل", "حالة الوكيل"}


def _direct_ready() -> bool:
    return bool(SHEET_ID and google_credentials.service_account_info())


def _webhook_ready() -> bool:
    return bool(WEBHOOK_URL and WEBHOOK_SECRET)


def configured():
    return _direct_ready() or _webhook_ready()


def _webhook(action, **kwargs):
    payload = {"secret": WEBHOOK_SECRET, "action": action, **kwargs}
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = urllib.request.urlopen(req, timeout=45)
    raw = response.read().decode("utf-8", errors="replace")
    try:
        result = json.loads(raw)
    except Exception as exc:
        status = getattr(response, "status", "?")
        content_type = response.headers.get("Content-Type", "unknown") if getattr(response, "headers", None) else "unknown"
        raise RuntimeError(
            f"Sheets webhook returned non-JSON response (HTTP {status}, content-type={content_type}, bytes={len(raw)})"
        ) from exc
    if not result.get("ok"):
        raise RuntimeError("Sheets webhook: " + str(result.get("error", "unknown"))[:300])
    return result


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        state = google_credentials.status()
        if state["present"]:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is present but is not valid service-account JSON")
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _SERVICE = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _SERVICE


def _direct_metadata():
    data = _service().spreadsheets().get(
        spreadsheetId=SHEET_ID, fields="sheets.properties"
    ).execute()
    return [
        {
            "title": s["properties"]["title"],
            "sheetId": s["properties"]["sheetId"],
            "rows": s["properties"].get("gridProperties", {}).get("rowCount", 0),
            "columns": s["properties"].get("gridProperties", {}).get("columnCount", 0),
        }
        for s in data.get("sheets", [])
    ]


def metadata():
    direct_error = None
    if _direct_ready():
        try:
            return _direct_metadata()
        except Exception as exc:
            direct_error = exc
    if _webhook_ready():
        try:
            return _webhook("metadata").get("sheets", [])
        except Exception as webhook_exc:
            if direct_error:
                raise RuntimeError(
                    f"Sheets direct failed: {type(direct_error).__name__}; webhook failed: {webhook_exc}"
                ) from webhook_exc
            raise
    if direct_error:
        raise direct_error
    state = google_credentials.status()
    if state["present"] and not state["valid"]:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is present but invalid")
    raise RuntimeError("Google Sheets is not configured")


def _column_letter(number: int) -> str:
    number = max(1, int(number))
    out = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        out = chr(65 + remainder) + out
    return out


def _direct_snapshot(max_rows=80, max_cols=16):
    out = {}
    sheets = _direct_metadata()
    by_title = {s["title"]: s for s in sheets}
    ordered = [by_title[t] for t in PRIORITY_TABS if t in by_title]
    ordered += [
        s for s in sheets
        if s["title"] not in PRIORITY_TABS and s["title"] not in EXCLUDED_CONTEXT_TABS
    ]
    for s in ordered[:18]:
        title = s["title"]
        row_limit = max(1, min(max_rows, int(s.get("rows") or max_rows)))
        col_limit = max(1, min(max_cols, int(s.get("columns") or max_cols)))
        end_col = _column_letter(col_limit)
        safe_title = title.replace("'", "''")
        values = _service().spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"'{safe_title}'!A1:{end_col}{row_limit}",
        ).execute().get("values", [])
        if values:
            out[title] = [r[:max_cols] for r in values]
    return out


def snapshot(max_rows=80, max_cols=16):
    max_rows = max(2, min(int(max_rows), 150))
    max_cols = max(2, min(int(max_cols), 20))
    direct_error = None
    if _direct_ready():
        try:
            return _direct_snapshot(max_rows=max_rows, max_cols=max_cols)
        except Exception as exc:
            direct_error = exc
    if _webhook_ready():
        try:
            return _webhook("snapshot", maxRows=max_rows, maxCols=max_cols).get("data", {})
        except Exception as webhook_exc:
            if direct_error:
                raise RuntimeError(
                    f"Sheets direct failed: {type(direct_error).__name__}; webhook failed: {webhook_exc}"
                ) from webhook_exc
            raise
    if direct_error:
        raise direct_error
    state = google_credentials.status()
    if state["present"] and not state["valid"]:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is present but invalid")
    raise RuntimeError("Google Sheets is not configured")


def search(query, max_results=25):
    query = (query or "").strip().lower()
    if not query:
        return []
    results = []
    for tab, rows in snapshot(150, 20).items():
        for idx, row in enumerate(rows, 1):
            if query in " | ".join(map(str, row)).lower():
                results.append({"sheet": tab, "row": idx, "values": row})
                if len(results) >= max_results:
                    return results
    return results


def _direct_update_cell(sheet, a1, value):
    safe_sheet = sheet.replace("'", "''")
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{safe_sheet}'!{a1}",
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()
    return {"ok": True, "sheet": sheet, "range": a1}


def update_cell(sheet, a1, value):
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,5}", a1 or ""):
        raise ValueError("Use one cell such as B12")
    titles = {s["title"] for s in metadata()}
    if sheet not in titles:
        raise ValueError("Unknown sheet: " + sheet)

    direct_error = None
    if _direct_ready():
        try:
            return _direct_update_cell(sheet, a1, value)
        except Exception as exc:
            direct_error = exc
    if _webhook_ready():
        try:
            return _webhook("update", sheet=sheet, range=a1, value=value, approved=True)
        except Exception as webhook_exc:
            if direct_error:
                raise RuntimeError(
                    f"Sheets direct update failed: {direct_error}; webhook failed: {webhook_exc}"
                ) from webhook_exc
            raise
    if direct_error:
        raise direct_error
    raise RuntimeError("Google Sheets update route is not configured")


def _direct_upsert_metrics(clean, sheet):
    titles = {s["title"] for s in _direct_metadata()}
    if sheet not in titles:
        raise ValueError("Unknown sheet: " + sheet)
    safe_sheet = sheet.replace("'", "''")
    values = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{safe_sheet}'!A:B"
    ).execute().get("values", [])
    labels = {str(row[0]): i + 1 for i, row in enumerate(values) if row}
    updates = []
    next_row = max(len(values) + 1, 1)
    for label, value in clean.items():
        row = labels.get(label)
        if row is None:
            row, next_row = next_row, next_row + 1
        updates.append({"range": f"'{safe_sheet}'!A{row}:B{row}", "values": [[label, value]]})
    _service().spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    return {"ok": True, "updated": len(updates), "route": "direct"}


def upsert_metrics(metrics, sheet="Executive_Brief"):
    if not isinstance(metrics, dict) or not metrics:
        return {"ok": True, "updated": 0}
    clean = {str(k)[:160]: str(v)[:5000] for k, v in metrics.items()}

    direct_error = None
    if _direct_ready():
        try:
            return _direct_upsert_metrics(clean, sheet)
        except Exception as exc:
            direct_error = exc
    if _webhook_ready():
        try:
            return _webhook("upsert_metrics", sheet=sheet, metrics=clean)
        except Exception as webhook_exc:
            if direct_error:
                raise RuntimeError(
                    f"Sheets direct metrics update failed: {direct_error}; webhook failed: {webhook_exc}"
                ) from webhook_exc
            raise
    if direct_error:
        raise direct_error
    raise RuntimeError("Google Sheets metrics route is not configured")


def compact_context(data=None, limit=12000):
    data = data if data is not None else snapshot()
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text[:limit]

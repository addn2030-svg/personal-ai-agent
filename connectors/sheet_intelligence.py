# -*- coding: utf-8 -*-
"""Safe Google Sheets read/search/update layer for Telegram intelligence."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid

from . import google_credentials

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
# Gateway v1.0: separate secret used only to record a human approval before a cell update.
APPROVAL_SECRET = os.environ.get("GOOGLE_SHEETS_APPROVAL_SECRET", "").strip()
_FORMULA_PREFIX = re.compile(r"^[=+\-@\t\r]")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
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


def _safe_cell(value):
    """Block formula injection (=, +, -, @) in text written with USER_ENTERED; keep plain numbers."""
    if isinstance(value, str) and _FORMULA_PREFIX.match(value) and not _PLAIN_NUMBER.match(value):
        return "'" + value
    return value


def _webhook(action, **kwargs):
    payload = {"secret": WEBHOOK_SECRET, "action": action, **kwargs}
    payload.setdefault("request_id", uuid.uuid4().hex)
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
    """Read the live workbook directly, tolerating an isolated bad tab."""
    out = {}
    errors = []
    sheets = _direct_metadata()
    by_title = {s["title"]: s for s in sheets}
    ordered = [by_title[t] for t in PRIORITY_TABS if t in by_title]
    ordered += [
        s for s in sheets
        if s["title"] not in PRIORITY_TABS and s["title"] not in EXCLUDED_CONTEXT_TABS
    ]

    attempted = 0
    for s in ordered[:18]:
        attempted += 1
        title = s["title"]
        row_limit = max(1, min(max_rows, int(s.get("rows") or max_rows)))
        col_limit = max(1, min(max_cols, int(s.get("columns") or max_cols)))
        end_col = _column_letter(col_limit)
        safe_title = title.replace("'", "''")
        a1 = f"'{safe_title}'!A1:{end_col}{row_limit}"
        try:
            values = _service().spreadsheets().values().get(
                spreadsheetId=SHEET_ID,
                range=a1,
            ).execute().get("values", [])
            if values:
                out[title] = [r[:max_cols] for r in values]
        except Exception as exc:
            safe = str(exc).replace("\n", " ")[:220]
            errors.append(f"{title}: {safe}")
            print(f"Sheets snapshot tab warning [{title}] range={a1}: {safe}", flush=True)

    if out:
        if errors:
            print(
                f"Sheets direct snapshot partial success: tabs={len(out)} failed={len(errors)}",
                flush=True,
            )
        return out

    if errors and attempted:
        raise RuntimeError(
            "Direct Sheets snapshot failed for all attempted tabs: " + " | ".join(errors[:3])
        )
    return {}


def snapshot(max_rows=80, max_cols=16):
    max_rows = max(2, min(int(max_rows), 150))
    max_cols = max(2, min(int(max_cols), 20))

    if _direct_ready():
        return _direct_snapshot(max_rows=max_rows, max_cols=max_cols)

    if _webhook_ready():
        return _webhook("snapshot", maxRows=max_rows, maxCols=max_cols).get("data", {})

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
        body={"values": [[_safe_cell(value)]]},
    ).execute()
    return {"ok": True, "sheet": sheet, "range": a1, "route": "direct"}


def _approval_id(approval_ref=None):
    ref = re.sub(r"[^A-Za-z0-9_\-:.]", "", str(approval_ref or ""))[:40]
    suffix = uuid.uuid4().hex[:12]
    return f"AP-{ref}-{suffix}" if ref else f"AP-{suffix}"


def _webhook_update_cell(sheet, a1, value, approved_by, approval_ref):
    if not APPROVAL_SECRET:
        raise RuntimeError("GOOGLE_SHEETS_APPROVAL_SECRET is not configured (required by Sheets gateway v1.0)")
    approval_id = _approval_id(approval_ref)
    _webhook(
        "record_approval",
        approval_secret=APPROVAL_SECRET,
        approval_id=approval_id,
        sheet=sheet,
        range=a1,
        value=value,
        approved_by=str(approved_by or "telegram_owner")[:100],
        ttl_minutes=15,
    )
    result = _webhook("update", sheet=sheet, range=a1, value=value, approval_id=approval_id)
    result["route"] = "webhook"
    return result


def update_cell(sheet, a1, value, approved_by="telegram_owner", approval_ref=None):
    """Execute an ALREADY human-approved single-cell change.

    Callers own PROPOSE/REVIEW/APPROVE. When the gateway is configured it is the only
    route (approval binding + Gateway_Audit). Direct Sheets API is a fallback only when
    the gateway is not configured.
    """
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,5}", a1 or ""):
        raise ValueError("Use one cell such as B12")
    titles = {s["title"] for s in metadata()}
    if sheet not in titles:
        raise ValueError("Unknown sheet: " + sheet)

    if _webhook_ready():
        return _webhook_update_cell(sheet, a1, value, approved_by, approval_ref)
    if _direct_ready():
        return _direct_update_cell(sheet, a1, value)
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
        updates.append({"range": f"'{safe_sheet}'!A{row}:B{row}", "values": [[label, _safe_cell(value)]]})
    _service().spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    return {"ok": True, "updated": len(updates), "route": "direct"}


def upsert_metrics(metrics, sheet="Executive_Brief"):
    if not isinstance(metrics, dict) or not metrics:
        return {"ok": True, "updated": 0}
    clean = {str(k)[:160]: str(v)[:5000] for k, v in metrics.items()}

    # A configured gateway is authoritative for every write so that metrics are
    # audited. Direct Sheets API remains a fallback only when the gateway is absent.
    if _webhook_ready():
        return _webhook("upsert_metrics", sheet=sheet, metrics=clean)
    if _direct_ready():
        return _direct_upsert_metrics(clean, sheet)
    raise RuntimeError("Google Sheets metrics route is not configured")


def compact_context(data=None, limit=12000):
    data = data if data is not None else snapshot()
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text[:limit]


_TAB_NAME_RE = re.compile(r"^[^\[\]\*\?:\\/'\"]{1,100}$", re.S)


def _validate_tab_name(title):
    title = (title or "").strip()
    if not title or not _TAB_NAME_RE.match(title):
        raise ValueError("Tab name must be 1-100 chars and cannot contain [ ] * ? : \\ / ' \"")
    return title


def _direct_add_tab(title, rows, cols):
    titles = {s["title"] for s in _direct_metadata()}
    if title in titles:
        return {"ok": True, "tab": title, "existed": True}
    body = {"requests": [{"addSheet": {"properties": {
        "title": title,
        "gridProperties": {"rowCount": int(rows), "columnCount": int(cols)},
    }}}]}
    result = _service().spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
    props = result.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
    return {"ok": True, "tab": props.get("title", title),
            "sheetId": props.get("sheetId"), "existed": False}


def add_tab(title, rows=1000, cols=26):
    """Create a new tab (idempotent). Callers decide approval; this layer validates and executes."""
    title = _validate_tab_name(title)

    # A configured gateway is authoritative for every write so that add-tab events
    # are audited. Direct Sheets API remains a fallback only when the gateway is absent.
    if _webhook_ready():
        return _webhook("addtab", title=title, rows=int(rows), cols=int(cols))
    if _direct_ready():
        return _direct_add_tab(title, int(rows), int(cols))
    raise RuntimeError("Google Sheets is not configured")

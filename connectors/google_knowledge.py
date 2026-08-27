# -*- coding: utf-8 -*-
"""Read-only Google knowledge gateway for production Telegram.

Uses the existing GOOGLE_SERVICE_ACCOUNT_JSON. No secrets or file contents are stored.
Allowed resource IDs are explicit to prevent arbitrary Drive traversal.
"""
from __future__ import annotations

import base64
import json
import os
import re

SERVICE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
PRIMARY_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
INDEX_SHEET_ID = "17RlQn1ePixFMSnWipTUALFE_zuGjMWz121IaLOLE2U4"
ALLOWED_FOLDER_IDS = [
    "1IKEeBHuqRaUEOCXL_xNSPVIs3UInFLDQ",
    "1V3w7lP0nZce6bVkj8c9dxYi4ASdtgIoJ",
    "1OVM6HCRhcOJyd62iFxcUhTlNU8rAOaOR",
    "1HNWIcitrgyKMKl5yc8AstG2fpSmTy1oI",
    "1S57W5ac7hD4ebINKZSLWV-XonwVHN",
    "1VE26NRhR8BaDxarLocNLK9hbwK9Nyt8g",
]
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
_DOC = "application/vnd.google-apps.document"
_SHEET = "application/vnd.google-apps.spreadsheet"
_FOLDER = "application/vnd.google-apps.folder"
_TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json"}


def _parse_service_json(raw: str) -> dict:
    """Accept common Railway secret formats without exposing the credential."""
    value = (raw or "").strip().lstrip("\ufeff")
    if not value:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON غير مضاف في Production")

    # A common mobile copy/paste mistake is putting NAME=value in the value field.
    prefix = "GOOGLE_SERVICE_ACCOUNT_JSON="
    if value.startswith(prefix):
        value = value[len(prefix):].strip()

    # Support a file path for local deployments.
    if os.path.isfile(value):
        with open(value, "r", encoding="utf-8") as fh:
            value = fh.read().strip().lstrip("\ufeff")

    candidates = [value]

    # Railway values sometimes contain a JSON string containing escaped JSON.
    try:
        outer = json.loads(value)
        if isinstance(outer, str):
            candidates.insert(0, outer.strip().lstrip("\ufeff"))
        elif isinstance(outer, dict):
            return outer
    except (json.JSONDecodeError, TypeError):
        pass

    # Also accept base64-encoded service-account JSON.
    try:
        padded = value + ("=" * (-len(value) % 4))
        decoded = base64.b64decode(padded, validate=True).decode("utf-8").strip().lstrip("\ufeff")
        if decoded:
            candidates.append(decoded)
    except Exception:
        pass

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, str):
                obj = json.loads(obj)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue

    raise RuntimeError(
        "GOOGLE_SERVICE_ACCOUNT_JSON موجود لكنه ليس JSON صالحًا. "
        "ضع محتوى ملف Service Account JSON فقط في قيمة المتغير، بدون اسم المتغير أو نص إضافي."
    )


def _info() -> dict:
    return _parse_service_json(SERVICE_JSON)


def service_account_email() -> str:
    try:
        return str(_info().get("client_email") or "")
    except Exception:
        return ""


def _services():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = _info()
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return (
        build("drive", "v3", credentials=creds, cache_discovery=False),
        build("sheets", "v4", credentials=creds, cache_discovery=False),
    )


def _id(value: str) -> str:
    value = (value or "").strip()
    for pat in (r"/spreadsheets/d/([A-Za-z0-9_-]+)", r"/document/d/([A-Za-z0-9_-]+)",
                r"/file/d/([A-Za-z0-9_-]+)", r"/folders/([A-Za-z0-9_-]+)"):
        m = re.search(pat, value)
        if m:
            return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
        return value
    raise ValueError("أرسل رابط Google Drive/Docs/Sheets صحيحًا أو File ID")


def allowed_spreadsheet_ids() -> set[str]:
    return {x for x in (PRIMARY_SHEET_ID, INDEX_SHEET_ID) if x}


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    email = service_account_email()
    if email:
        text = text.replace(email, "[SERVICE_ACCOUNT]")
    return text[:240]


def access_report() -> dict:
    try:
        info = _info()
        email = str(info.get("client_email") or "")
        if not email:
            raise RuntimeError("Service Account JSON لا يحتوي client_email")
        drive, sheets = _services()
    except Exception as exc:
        return {
            "credential_ok": False,
            "credential_error": _safe_error(exc),
            "service_account": "غير صالح",
            "spreadsheets": [],
            "folders": [],
        }

    report = {
        "credential_ok": True,
        "credential_error": "",
        "service_account": email,
        "spreadsheets": [],
        "folders": [],
    }
    for sid in sorted(allowed_spreadsheet_ids()):
        row = {"id": sid, "ok": False, "title": ""}
        try:
            meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="properties.title").execute()
            row.update(ok=True, title=(meta.get("properties") or {}).get("title", ""))
        except Exception as exc:
            row["error"] = _safe_error(exc)
        report["spreadsheets"].append(row)
    for fid in ALLOWED_FOLDER_IDS:
        row = {"id": fid, "ok": False, "title": ""}
        try:
            meta = drive.files().get(fileId=fid, fields="id,name,mimeType", supportsAllDrives=True).execute()
            row.update(ok=meta.get("mimeType") == _FOLDER, title=meta.get("name", ""))
        except Exception as exc:
            row["error"] = _safe_error(exc)
        report["folders"].append(row)
    return report


def _folder_items(drive, folder_id: str, max_items: int = 120) -> list[dict]:
    out, token = [], None
    while len(out) < max_items:
        res = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            pageSize=min(100, max_items - len(out)),
            pageToken=token,
            fields="nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        out.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return out


def search(query: str, max_results: int = 20) -> list[dict]:
    query = (query or "").strip().lower()
    if not query:
        raise ValueError("اكتب كلمة البحث بعد /knowledge")
    drive, sheets = _services()
    results = []

    try:
        meta = sheets.spreadsheets().get(spreadsheetId=INDEX_SHEET_ID, fields="sheets.properties.title").execute()
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        for tab in tabs[:12]:
            rows = sheets.spreadsheets().values().get(
                spreadsheetId=INDEX_SHEET_ID, range=f"'{tab}'!A1:H250"
            ).execute().get("values", [])
            for row in rows[1:]:
                text = " | ".join(map(str, row)).lower()
                if query in text:
                    results.append({"source": "index", "tab": tab, "name": row[1] if len(row) > 1 else "", "url": row[4] if len(row) > 4 else ""})
                    if len(results) >= max_results:
                        return results
    except Exception:
        pass

    for fid in ALLOWED_FOLDER_IDS:
        try:
            for item in _folder_items(drive, fid, max_items=100):
                if query in str(item.get("name", "")).lower():
                    results.append({"source": "folder", "folder_id": fid, "name": item.get("name", ""), "url": item.get("webViewLink", ""), "mimeType": item.get("mimeType", "")})
                    if len(results) >= max_results:
                        return results
        except Exception:
            continue
    return results


def _is_allowed_file(drive, file_id: str) -> bool:
    if file_id in allowed_spreadsheet_ids():
        return True
    meta = drive.files().get(fileId=file_id, fields="id,parents", supportsAllDrives=True).execute()
    parents = set(meta.get("parents") or [])
    return bool(parents.intersection(ALLOWED_FOLDER_IDS))


def read(value: str, max_chars: int = 12000) -> dict:
    file_id = _id(value)
    drive, sheets = _services()
    if not _is_allowed_file(drive, file_id):
        raise PermissionError("هذا الملف خارج قائمة مصادر المعرفة المسموحة للبوت")
    meta = drive.files().get(fileId=file_id, fields="id,name,mimeType,webViewLink", supportsAllDrives=True).execute()
    mime = meta.get("mimeType", "")
    text = ""
    if mime == _DOC:
        data = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
    elif mime == _SHEET:
        smeta = sheets.spreadsheets().get(spreadsheetId=file_id, fields="sheets.properties.title").execute()
        chunks = []
        for tab in [s["properties"]["title"] for s in smeta.get("sheets", [])][:12]:
            rows = sheets.spreadsheets().values().get(spreadsheetId=file_id, range=f"'{tab}'!A1:T80").execute().get("values", [])
            if rows:
                chunks.append(f"[{tab}]\n" + "\n".join(" | ".join(map(str, r)) for r in rows))
        text = "\n\n".join(chunks)
    elif mime in _TEXT_TYPES:
        data = drive.files().get_media(fileId=file_id).execute()
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
    else:
        return {"name": meta.get("name", ""), "url": meta.get("webViewLink", ""), "mimeType": mime, "text": "", "note": "القراءة النصية لهذا النوع ستضاف لاحقًا؛ يمكن للبوت الآن رؤية الملف ومعلوماته."}
    return {"name": meta.get("name", ""), "url": meta.get("webViewLink", ""), "mimeType": mime, "text": text[:max_chars]}


def sheet_summary(value: str) -> dict:
    sid = _id(value)
    if sid not in allowed_spreadsheet_ids():
        raise PermissionError("هذا الشيت غير موجود في قائمة الشيتات المسموحة")
    _, sheets = _services()
    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties(title,gridProperties)").execute()
    return {
        "id": sid,
        "title": (meta.get("properties") or {}).get("title", ""),
        "tabs": [s["properties"].get("title", "") for s in meta.get("sheets", [])],
    }

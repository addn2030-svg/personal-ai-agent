# -*- coding: utf-8 -*-
"""Read-only Google knowledge access through the existing Apps Script webhook.

This avoids requiring a valid service-account JSON in Railway. The Apps Script
runs under the Google account that owns the deployment and enforces its own
allowlist plus AGENT_SECRET authentication.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
INDEX_SHEET_ID = "17RlQn1ePixFMSnWipTUALFE_zuGjMWz121IaLOLE2U4"
PRIMARY_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
ALLOWED_FOLDER_IDS = [
    "1IKEeBHuqRaUEOCXL_xNSPVIs3UInFLDQ",
    "1V3w7lP0nZce6bVkj8c9dxYi4ASdtgIoJ",
    "1OVM6HCRhcOJyd62iFxcUhTlNU8rAOaOR",
    "1HNWIcitrgyKMKl5yc8AstG2fpSmTy1oI",
    "1S57W5ac7hD4ebINKZSLWV-XonwVHN",
    "1VE26NRhR8BaDxarLocNLK9hbwK9Nyt8g",
]


def configured() -> bool:
    return bool(WEBHOOK_URL and WEBHOOK_SECRET)


def _id(value: str) -> str:
    value = (value or "").strip()
    for pat in (
        r"/spreadsheets/d/([A-Za-z0-9_-]+)",
        r"/document/d/([A-Za-z0-9_-]+)",
        r"/file/d/([A-Za-z0-9_-]+)",
        r"/folders/([A-Za-z0-9_-]+)",
    ):
        match = re.search(pat, value)
        if match:
            return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
        return value
    raise ValueError("أرسل رابط Google Drive/Docs/Sheets صحيحًا أو File ID")


def allowed_spreadsheet_ids() -> set[str]:
    return {x for x in (PRIMARY_SHEET_ID, INDEX_SHEET_ID) if x}


def _call(action: str, **payload) -> dict:
    if not configured():
        raise RuntimeError("Google Apps Script gateway غير مهيأ في Railway")
    body = {"secret": WEBHOOK_SECRET, "action": action}
    body.update(payload)
    request = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8", errors="replace").strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Google Apps Script أعاد استجابة غير JSON؛ حدّث Deployment إلى v0.8") from exc
    if not result.get("ok"):
        error = str(result.get("error") or "unknown error")
        if "unsupported action" in error.lower():
            raise RuntimeError("Google Apps Script المنشور قديم؛ حدّث Deployment إلى Google Gateway v0.8")
        raise RuntimeError("Google Apps Script: " + error[:240])
    return result


def access_report() -> dict:
    try:
        result = _call("knowledge_access")
        return {
            "credential_ok": True,
            "credential_error": "",
            "service_account": "Google Apps Script Gateway ✅",
            "gateway": "apps_script",
            "spreadsheets": result.get("spreadsheets", []),
            "folders": result.get("folders", []),
        }
    except Exception as exc:
        return {
            "credential_ok": False,
            "credential_error": str(exc)[:300],
            "service_account": "Google Apps Script Gateway",
            "gateway": "apps_script",
            "spreadsheets": [],
            "folders": [],
        }


def search(query: str, max_results: int = 20) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise ValueError("اكتب كلمة البحث بعد /knowledge")
    result = _call("knowledge_search", query=query, maxResults=max(1, min(int(max_results), 30)))
    return list(result.get("results") or [])


def read(value: str, max_chars: int = 12000) -> dict:
    file_id = _id(value)
    result = _call("knowledge_read", fileId=file_id, maxChars=max(1000, min(int(max_chars), 16000)))
    return {
        "name": result.get("name", ""),
        "url": result.get("url", ""),
        "mimeType": result.get("mimeType", ""),
        "text": result.get("text", ""),
        "note": result.get("note", ""),
    }


def sheet_summary(value: str) -> dict:
    spreadsheet_id = _id(value)
    if spreadsheet_id not in allowed_spreadsheet_ids():
        raise PermissionError("هذا الشيت غير موجود في قائمة الشيتات المسموحة")
    result = _call("sheetcheck", spreadsheetId=spreadsheet_id)
    return {
        "id": spreadsheet_id,
        "title": result.get("title", ""),
        "tabs": list(result.get("tabs") or []),
    }

# -*- coding: utf-8 -*-
"""Direct, privacy-separated Google Sheets route for clinical cases.

Clinical Telegram records must never use the operational workbook or its Apps
Script webhook. This connector uses the validated Google service account and a
separate spreadsheet ID. The tab may be set explicitly with
``CLINICAL_SHEET_TAB``; when it is omitted, the first existing tab is resolved
from the workbook metadata rather than inventing a tab name.

No credential or patient content is logged by this module.
"""
from __future__ import annotations

import os
from typing import Any

from . import google_credentials

DEFAULT_CLINICAL_SHEET_ID = "1Te-dD6B9USOzURbTjMoZQgYtDeoygwR6QRGeHHGAzaQ"
DEFAULT_CLINICAL_SHEET_TAB = ""
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SERVICE = None


def sheet_id() -> str:
    return os.environ.get("CLINICAL_SHEET_ID", DEFAULT_CLINICAL_SHEET_ID).strip()


def configured() -> bool:
    """Return whether the dedicated direct-write route has local configuration."""
    return bool(sheet_id() and google_credentials.service_account_info())


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("Google service-account JSON is missing or invalid")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=_SCOPES
    )
    _SERVICE = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _SERVICE


def _tab(service) -> str:
    explicit = os.environ.get("CLINICAL_SHEET_TAB", DEFAULT_CLINICAL_SHEET_TAB).strip()
    if explicit:
        return explicit

    metadata = service.spreadsheets().get(
        spreadsheetId=sheet_id(),
        fields="sheets.properties.title",
    ).execute()
    titles = [
        str(item.get("properties", {}).get("title", "")).strip()
        for item in metadata.get("sheets", [])
    ]
    titles = [title for title in titles if title]
    if not titles:
        raise RuntimeError(
            "Clinical workbook has no readable tab; set CLINICAL_SHEET_TAB explicitly"
        )
    return titles[0]


def _append(row: list[Any]):
    if not configured():
        raise RuntimeError(
            "Clinical Sheets route is not configured; set GOOGLE_SERVICE_ACCOUNT_JSON"
        )
    service = _service()
    tab = _tab(service).replace("'", "''")
    return service.spreadsheets().values().append(
        spreadsheetId=sheet_id(),
        range=f"'{tab}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def append_intake(
    *,
    intake_id: str,
    timestamp: str,
    chat_id: str,
    kind: str,
    text: str,
    language: str,
    status: str,
    response_id: str = "",
    error: str = "",
):
    """Append one clinical intake record to the dedicated workbook."""
    return _append([
        "INTAKE",
        intake_id,
        timestamp,
        chat_id,
        kind,
        text,
        language,
        "CLINICAL_PRIVATE",
        "RESTRICTED",
        status,
        response_id,
        error,
    ])


def append_conversation(
    *,
    conversation_id: str,
    intake_id: str,
    timestamp: str,
    provider: str,
    model: str,
    question: str,
    answer: str,
    input_tokens: Any = "",
    output_tokens: Any = "",
    latency_ms: Any = "",
    status: str = "",
    error: str = "",
):
    """Append one clinical model exchange to the dedicated workbook."""
    return _append([
        "CONVERSATION",
        conversation_id,
        intake_id,
        timestamp,
        provider,
        model,
        question,
        answer,
        input_tokens,
        output_tokens,
        latency_ms,
        status,
        "PENDING_REVIEW",
        error,
    ])


def status() -> dict:
    """Return non-secret configuration truth for diagnostics."""
    explicit_tab = os.environ.get("CLINICAL_SHEET_TAB", "").strip()
    return {
        "configured": configured(),
        "sheet_id_configured": bool(sheet_id()),
        "service_account_configured": bool(google_credentials.service_account_info()),
        "tab": explicit_tab or "first workbook tab (auto-resolved)",
        "direct_write": configured(),
    }

# -*- coding: utf-8 -*-
"""Fail-closed Google Sheets adapter for Possibility Stack shadow testing.

The adapter is not imported by Telegram or startup code. It can only write when
both strategic reasoning and the dedicated DEV write flag are enabled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from connectors import google_credentials
from connectors.strategic_creator import PossibilityProposal, SHEET_COLUMNS

DEV_TITLE_PREFIX = "DEV — Personal AI Agent"
DEV_TAB = "Possibility_Stack_DEV"
_SERVICE = None


@dataclass(frozen=True)
class ShadowReceipt:
    spreadsheet_id: str
    sheet: str
    updated_range: str
    possibility_id: str
    verified: bool


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


def configured() -> bool:
    return bool(
        _flag("AI_STRATEGIC_CREATOR_ENABLED")
        and _flag("POSSIBILITY_DEV_WRITE_ENABLED")
        and os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
        and google_credentials.service_account_info()
    )


def _target_id() -> str:
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not _flag("AI_STRATEGIC_CREATOR_ENABLED"):
        raise RuntimeError("Strategic Creator is disabled")
    if not _flag("POSSIBILITY_DEV_WRITE_ENABLED"):
        raise RuntimeError("Possibility DEV writes are disabled")
    if not dev_id:
        raise RuntimeError("POSSIBILITY_DEV_SHEET_ID is missing")
    if live_id and dev_id == live_id:
        raise RuntimeError("Refusing to write to the live Google Sheet")
    if not DEV_TAB.endswith("_DEV"):
        raise RuntimeError("DEV tab safety invariant failed")
    return dev_id


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("Valid Google service-account credentials are required")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _SERVICE = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _SERVICE


def _preflight(service, spreadsheet_id: str) -> None:
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="properties.title,sheets.properties",
    ).execute()
    title = str((meta.get("properties") or {}).get("title") or "")
    if not title.startswith(DEV_TITLE_PREFIX):
        raise RuntimeError("Target workbook is not an approved DEV copy")
    titles = {
        str((item.get("properties") or {}).get("title") or "")
        for item in meta.get("sheets", [])
    }
    if DEV_TAB not in titles:
        raise RuntimeError("Possibility DEV tab is missing")

    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A1:P1",
    ).execute().get("values", [])
    headers = tuple(values[0]) if values else ()
    if headers != SHEET_COLUMNS:
        raise RuntimeError("Possibility Stack header/schema mismatch")


def append_proposal(proposal: PossibilityProposal, *, service=None) -> ShadowReceipt:
    """Append one PROPOSED row to the DEV workbook and verify the receipt."""
    spreadsheet_id = _target_id()
    row = proposal.to_row()
    if row["Status"] != "PROPOSED" or row["User_Approval"] != "REQUIRED":
        raise RuntimeError("Only approval-gated proposals may enter the shadow sheet")

    api = service or _service()
    _preflight(api, spreadsheet_id)

    existing = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A2:A300",
    ).execute().get("values", [])
    if any(values and values[0] == row["Possibility_ID"] for values in existing):
        raise RuntimeError("Duplicate possibility_id")

    ordered = [row[name] for name in SHEET_COLUMNS]
    result = api.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A:P",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        includeValuesInResponse=True,
        body={"values": [ordered]},
    ).execute()
    updates = result.get("updates") or {}
    updated_range = str(updates.get("updatedRange") or "")
    if not updated_range.startswith(f"'{DEV_TAB}'!") and not updated_range.startswith(f"{DEV_TAB}!"):
        raise RuntimeError("Google Sheets did not return a DEV-tab receipt")

    readback = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=updated_range,
    ).execute().get("values", [])
    verified = bool(readback and readback[0] and readback[0][0] == row["Possibility_ID"])
    if not verified:
        raise RuntimeError("Possibility append could not be verified")

    return ShadowReceipt(
        spreadsheet_id=spreadsheet_id,
        sheet=DEV_TAB,
        updated_range=updated_range,
        possibility_id=row["Possibility_ID"],
        verified=True,
    )


def status() -> dict:
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    return {
        "configured": configured(),
        "strategic_enabled": _flag("AI_STRATEGIC_CREATOR_ENABLED"),
        "dev_write_enabled": _flag("POSSIBILITY_DEV_WRITE_ENABLED"),
        "dev_sheet_present": bool(dev_id),
        "target_is_live": bool(dev_id and live_id and dev_id == live_id),
        "tab": DEV_TAB,
        "startup_integrated": False,
    }

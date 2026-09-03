# -*- coding: utf-8 -*-
"""Fail-closed DEV writer for prepared Strategic Creator comparisons.

Only generated outputs and Review_Status are updated. Human rating columns are
never written by this adapter.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from connectors import google_credentials
from evaluation import strategic_shadow_cases as catalog
from evaluation.strategic_shadow_case_runner import PreparedComparison

DEV_TITLE_PREFIX = "DEV — Personal AI Agent"
DEV_TAB = "Shadow_Test_Cases_DEV"
WRITE_CONFIRMATION = "WRITE_PREPARED_SHADOW_CASES"
_SERVICE = None


@dataclass(frozen=True)
class CaseWriteReceipt:
    spreadsheet_id: str
    sheet: str
    case_ids: tuple[str, ...]
    updated_rows: int
    verified: bool


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


def _target_id() -> str:
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not _flag("AI_STRATEGIC_CREATOR_ENABLED"):
        raise RuntimeError("Strategic Creator is disabled")
    if not _flag("SHADOW_CASE_DEV_WRITE_ENABLED"):
        raise RuntimeError("Shadow case DEV writes are disabled")
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


def _preflight(api, spreadsheet_id: str) -> list[list]:
    meta = api.spreadsheets().get(
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
        raise RuntimeError("Shadow test case DEV tab is missing")
    values = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A1:M100",
    ).execute().get("values", [])
    headers = tuple(values[0]) if values else ()
    if headers != catalog.SHEET_COLUMNS:
        raise RuntimeError("Shadow test case header/schema mismatch")
    return values[1:]


def _validate(comparisons: Iterable[PreparedComparison]) -> list[PreparedComparison]:
    items = list(comparisons)
    expected = [case.case_id for case in catalog.CASES]
    actual = [item.case_id for item in items]
    if actual != expected:
        raise ValueError("Prepared comparisons must contain the complete ordered catalog")
    for item in items:
        if not item.passed or item.external_writes != 0:
            raise ValueError(f"{item.case_id} did not pass no-write preparation")
        if tuple(item.row) != catalog.SHEET_COLUMNS:
            raise ValueError(f"{item.case_id} schema mismatch")
        if item.row["Review_Status"] != "READY_FOR_REVIEW":
            raise ValueError(f"{item.case_id} is not ready for review")
        if not item.row["Baseline_Output"] or not item.row["Strategic_Output"]:
            raise ValueError(f"{item.case_id} outputs are missing")
        for name in (
            "Baseline_Useful", "Candidate_Useful", "Preferred",
            "Safety_Passed", "Evidence_Discipline", "Reviewer_Note",
        ):
            if item.row[name] not in ("", None):
                raise ValueError(f"{item.case_id} contains a pre-filled human judgment")
    return items


def write_prepared_cases(
    comparisons: Iterable[PreparedComparison],
    confirmation: str,
    *,
    service=None,
) -> CaseWriteReceipt:
    if confirmation != WRITE_CONFIRMATION:
        raise RuntimeError("Exact prepared-case DEV confirmation is required")
    items = _validate(comparisons)
    spreadsheet_id = _target_id()
    api = service or _service()
    existing = _preflight(api, spreadsheet_id)

    positions: dict[str, tuple[int, str]] = {}
    expected_ids = {case.case_id for case in catalog.CASES}
    for row_number, values in enumerate(existing, start=2):
        padded = list(values[:13]) + [""] * max(0, 13 - len(values))
        case_id = str(padded[0]).strip()
        if case_id not in expected_ids:
            continue
        if case_id in positions:
            raise RuntimeError(f"Duplicate Case_ID in DEV sheet: {case_id}")
        status = str(padded[12]).strip()
        if status not in {"NOT_RUN", "READY_FOR_REVIEW"}:
            raise RuntimeError(f"Refusing to overwrite reviewed case: {case_id}")
        positions[case_id] = (row_number, status)
    missing = expected_ids - set(positions)
    if missing:
        raise RuntimeError("Missing DEV Case_ID: " + ", ".join(sorted(missing)))

    data = []
    for item in items:
        row_number, _status = positions[item.case_id]
        data.extend([
            {
                "range": f"'{DEV_TAB}'!E{row_number}:F{row_number}",
                "values": [[
                    item.row["Baseline_Output"],
                    item.row["Strategic_Output"],
                ]],
            },
            {
                "range": f"'{DEV_TAB}'!M{row_number}",
                "values": [["READY_FOR_REVIEW"]],
            },
        ])
    api.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()

    readback = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A2:M100",
    ).execute().get("values", [])
    verified = {}
    for values in readback:
        padded = list(values[:13]) + [""] * max(0, 13 - len(values))
        case_id = str(padded[0]).strip()
        if case_id in expected_ids:
            verified[case_id] = bool(padded[4] and padded[5] and padded[12] == "READY_FOR_REVIEW")
    if set(verified) != expected_ids or not all(verified.values()):
        raise RuntimeError("Prepared shadow case write could not be verified")
    return CaseWriteReceipt(
        spreadsheet_id=spreadsheet_id,
        sheet=DEV_TAB,
        case_ids=tuple(item.case_id for item in items),
        updated_rows=len(items),
        verified=True,
    )

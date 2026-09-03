# -*- coding: utf-8 -*-
"""DEV-only adapter for human Strategic Creator shadow reviews."""
from __future__ import annotations

import os
from dataclasses import dataclass

from connectors import google_credentials
from evaluation.strategic_shadow_acceptance import (
    ReviewedRun,
    SHEET_COLUMNS,
    acceptance_report,
)

DEV_TITLE_PREFIX = "DEV — Personal AI Agent"
DEV_TAB = "Shadow_Acceptance_DEV"
WRITE_CONFIRMATION = "RECORD_HUMAN_SHADOW_REVIEW"
_SERVICE = None


@dataclass(frozen=True)
class ReviewReceipt:
    spreadsheet_id: str
    sheet: str
    updated_range: str
    run_id: str
    verified: bool


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


def _target_id() -> str:
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not dev_id:
        raise RuntimeError("POSSIBILITY_DEV_SHEET_ID is missing")
    if live_id and dev_id == live_id:
        raise RuntimeError("Refusing to use the live Google Sheet")
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


def _preflight(api, spreadsheet_id: str) -> None:
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
    if DEV_TAB not in titles or not DEV_TAB.endswith("_DEV"):
        raise RuntimeError("Shadow acceptance DEV tab is missing")
    values = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A1:P1",
    ).execute().get("values", [])
    headers = tuple(values[0]) if values else ()
    if headers != SHEET_COLUMNS:
        raise RuntimeError("Shadow acceptance header/schema mismatch")


def _bool(value, label: str) -> bool:
    if value is True or str(value).strip().upper() == "TRUE":
        return True
    if value is False or str(value).strip().upper() == "FALSE":
        return False
    raise ValueError(f"{label} must be TRUE or FALSE")


def _ratio(value, label: str) -> float:
    try:
        result = float(value)
    except Exception as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _parse_row(values: list) -> ReviewedRun | None:
    padded = list(values[:16]) + [""] * max(0, 16 - len(values))
    data = dict(zip(SHEET_COLUMNS, padded))
    run_id = str(data["Run_ID"]).strip()
    decision = str(data["Decision"]).strip().upper()
    if not run_id or run_id.startswith("SR-TEST-") or decision == "TEST_ONLY":
        return None
    return ReviewedRun(
        run_id=run_id,
        review_date=str(data["Review_Date"]).strip(),
        domain=str(data["Domain"]).strip(),
        scenario=str(data["Scenario"]).strip(),
        baseline_useful=_bool(data["Baseline_Useful"], "Baseline_Useful"),
        candidate_useful=_bool(data["Candidate_Useful"], "Candidate_Useful"),
        preferred=str(data["Preferred"]).strip().upper(),
        safety_passed=_bool(data["Safety_Passed"], "Safety_Passed"),
        schema_passed=_bool(data["Schema_Passed"], "Schema_Passed"),
        no_external_claim=_bool(data["No_External_Claim"], "No_External_Claim"),
        evidence_discipline=_bool(data["Evidence_Discipline"], "Evidence_Discipline"),
        latency_ratio=_ratio(data["Latency_Ratio"], "Latency_Ratio"),
        cost_ratio=_ratio(data["Cost_Ratio"], "Cost_Ratio"),
        reviewer_note=str(data["Reviewer_Note"]).strip(),
    )


def read_acceptance_report(*, service=None) -> dict:
    spreadsheet_id = _target_id()
    api = service or _service()
    _preflight(api, spreadsheet_id)
    rows = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A2:P200",
    ).execute().get("values", [])
    reviews = []
    for index, values in enumerate(rows, start=2):
        try:
            item = _parse_row(values)
        except Exception as exc:
            raise ValueError(f"Invalid review row {index}: {exc}") from exc
        if item is not None:
            reviews.append(item)
    report = acceptance_report(reviews)
    report["source"] = "DEV_SHEET_HUMAN_REVIEWS"
    report["ignored_test_rows"] = len(rows) - len(reviews)
    return report


def append_review(
    review: ReviewedRun,
    confirmation: str,
    *,
    service=None,
) -> ReviewReceipt:
    if not _flag("SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED"):
        raise RuntimeError("Shadow acceptance DEV writes are disabled")
    if confirmation != WRITE_CONFIRMATION:
        raise RuntimeError("Exact human-review confirmation is required")
    spreadsheet_id = _target_id()
    row = review.to_row()
    api = service or _service()
    _preflight(api, spreadsheet_id)

    existing = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A2:A200",
    ).execute().get("values", [])
    if any(values and values[0] == review.run_id for values in existing):
        raise RuntimeError("Duplicate Run_ID")

    ordered = [row[name] for name in SHEET_COLUMNS]
    result = api.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{DEV_TAB}'!A:P",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        includeValuesInResponse=True,
        body={"values": [ordered]},
    ).execute()
    updated_range = str(((result.get("updates") or {}).get("updatedRange")) or "")
    if not updated_range.startswith(f"'{DEV_TAB}'!") and not updated_range.startswith(f"{DEV_TAB}!"):
        raise RuntimeError("Google Sheets did not return a DEV review receipt")
    readback = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=updated_range,
    ).execute().get("values", [])
    if not (readback and readback[0] and readback[0][0] == review.run_id):
        raise RuntimeError("Review append could not be verified")
    return ReviewReceipt(
        spreadsheet_id=spreadsheet_id,
        sheet=DEV_TAB,
        updated_range=updated_range,
        run_id=review.run_id,
        verified=True,
    )

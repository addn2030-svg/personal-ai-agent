# -*- coding: utf-8 -*-
"""Unified connection status for Abdulrahman AI OS integrations.

Implements the summary checklist of docs/connection-guide.md against the real
environment variables the code reads, with optional live API probes.

Usage:
  python3 -m connectors.connection_setup             # config checks only (no network)
  python3 -m connectors.connection_setup --live      # + live API probes (network)
  python3 -m connectors.connection_setup --json      # machine-readable output
  python3 -m connectors.connection_setup --guide calendar   # setup steps for one integration

Never prints secret values — only presence/validity metadata.
"""
from __future__ import annotations

import json
import os
import sys

from . import google_credentials

SHEETS_READONLY = "https://www.googleapis.com/auth/spreadsheets.readonly"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

GUIDES = {
    "telegram": [
        "Already active — the Telegram bot is the interaction channel.",
        "Rotating the token: talk to @BotFather → /revoke, then set TELEGRAM_BOT_TOKEN again.",
    ],
    "sheets": [
        "console.cloud.google.com → Create project: \"Abdulrahman AI OS\".",
        "APIs & Services → enable \"Google Sheets API\" (and \"Google Drive API\").",
        "Credentials → Create Credentials → Service Account → name: abdulrahman-agent → download JSON key.",
        "Set GOOGLE_SERVICE_ACCOUNT_JSON to the JSON (inline, base64, or a file path).",
        "Set GOOGLE_SHEET_ID (the id between /d/ and /edit in the sheet URL).",
        "Share the Google Sheet with the service-account email (Editor).",
    ],
    "drive": [
        "Same service account as Sheets — no new credentials.",
        "APIs & Services → enable \"Google Drive API\".",
        "Set GOOGLE_DRIVE_FOLDER_ID (the folder id in the Drive URL).",
        "Share the target Drive folder with the service-account email (Editor).",
    ],
    "docs": [
        "Same service account — no new credentials.",
        "APIs & Services → enable \"Google Docs API\".",
        "Open your letter/report Doc → Share → service-account email (Editor).",
        "Set GOOGLE_DOCS_DOCUMENT_ID (the id between /d/ and /edit in the doc URL).",
        "New letters land in GOOGLE_DRIVE_FOLDER_ID when that is set.",
    ],
    "calendar": [
        "APIs & Services → enable \"Google Calendar API\".",
        "Google Calendar ⚙️ Settings → your calendar → \"Share with specific people\"",
        "  → service-account email → \"Make changes to events\".",
        "Same settings page → \"Integrate calendar\" → copy the Calendar ID",
        "  → set GOOGLE_CALENDAR_ID (required for the service-account path; "
        "the literal value 'primary' does not work for service accounts).",
    ],
    "github": [
        "github.com → Settings → Developer settings → Personal access tokens.",
        "Generate a token with repo (and workflow, if CI pushes are needed) scopes.",
        "Set GITHUB_TOKEN locally / in the deployment variables — never in chat or git.",
        "Set AI_OS_GITHUB_REPO (default: addn2030-svg/personal-ai-agent).",
    ],
}

PRIORITY_ORDER = ["calendar", "docs", "github"]  # per the guide: meeting Sept 14 → letters → backup


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def check_telegram(env=None) -> dict:
    env = env if env is not None else _env
    token = env("TELEGRAM_BOT_TOKEN")
    return {
        "key": "telegram", "name": "Telegram Bot", "env": ["TELEGRAM_BOT_TOKEN"],
        "status": "ok" if token else "missing",
        "detail": "token set — bot channel configured" if token else "TELEGRAM_BOT_TOKEN is not set",
    }


def check_sheets(env=None) -> dict:
    env = env if env is not None else _env
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    info = google_credentials.service_account_info(raw) if raw else None
    sheet_id = env("GOOGLE_SHEET_ID")
    webhook = bool(env("GOOGLE_SHEETS_WEBHOOK_URL") and env("GOOGLE_SHEETS_WEBHOOK_SECRET"))
    if raw and not info:
        status, detail = "invalid", "GOOGLE_SERVICE_ACCOUNT_JSON is present but not a valid service-account key"
    elif not info and not webhook:
        status = "missing"
        detail = "set GOOGLE_SERVICE_ACCOUNT_JSON (+ GOOGLE_SHEET_ID) or the Apps-Script webhook pair"
    elif not sheet_id and not webhook:
        status = "partial"
        detail = "credentials valid — GOOGLE_SHEET_ID not set (direct read needs it)"
    else:
        mode = "direct" if (info and sheet_id) else "webhook"
        status, detail = "ok", f"credentials valid, sheet id set ({mode} path configured)"
    return {"key": "sheets", "name": "Google Sheets",
            "env": ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID"],
            "status": status, "detail": detail}


def check_drive(env=None) -> dict:
    env = env if env is not None else _env
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    info = google_credentials.service_account_info(raw) if raw else None
    folder_id = env("GOOGLE_DRIVE_FOLDER_ID")
    if raw and not info:
        status, detail = "invalid", "GOOGLE_SERVICE_ACCOUNT_JSON is present but invalid"
    elif not info:
        status, detail = "missing", "GOOGLE_SERVICE_ACCOUNT_JSON not set (shared with Sheets/Docs/Calendar)"
    elif not folder_id:
        status, detail = "partial", "credentials valid — set GOOGLE_DRIVE_FOLDER_ID and share the folder"
    else:
        status, detail = "ok", "credentials valid, target folder configured"
    return {"key": "drive", "name": "Google Drive",
            "env": ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DRIVE_FOLDER_ID"],
            "status": status, "detail": detail}


def check_docs(env=None) -> dict:
    env = env if env is not None else _env
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    info = google_credentials.service_account_info(raw) if raw else None
    doc_id = env("GOOGLE_DOCS_DOCUMENT_ID")
    if raw and not info:
        status, detail = "invalid", "GOOGLE_SERVICE_ACCOUNT_JSON is present but invalid"
    elif not info:
        status, detail = "missing", "GOOGLE_SERVICE_ACCOUNT_JSON not set (shared with Sheets/Drive/Calendar)"
    elif not doc_id:
        status, detail = "partial", (
            "credentials valid — creation works now; set GOOGLE_DOCS_DOCUMENT_ID "
            "for the default letter/report document"
        )
    else:
        status, detail = "ok", "credentials valid, default document configured"
    return {"key": "docs", "name": "Google Docs",
            "env": ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DOCS_DOCUMENT_ID"],
            "status": status, "detail": detail}


def check_calendar(env=None) -> dict:
    env = env if env is not None else _env
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON") or env("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON")
    info = google_credentials.service_account_info(raw) if raw else None
    calendar_id = env("GOOGLE_CALENDAR_ID")
    if raw and not info:
        status, detail = "invalid", "service-account JSON is present but invalid"
    elif not info:
        status, detail = "missing", "GOOGLE_SERVICE_ACCOUNT_JSON not set"
    elif not calendar_id or calendar_id == "primary":
        status, detail = "partial", (
            "credentials valid — share the calendar with the service-account email and set "
            "GOOGLE_CALENDAR_ID to the real calendar id (not 'primary')"
        )
    else:
        status, detail = "ok", "credentials valid, calendar id configured"
    return {"key": "calendar", "name": "Google Calendar",
            "env": ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CALENDAR_ID"],
            "status": status, "detail": detail}


def check_github(env=None) -> dict:
    env = env if env is not None else _env
    token = env("GITHUB_TOKEN")
    repo = env("AI_OS_GITHUB_REPO") or "addn2030-svg/personal-ai-agent"
    return {
        "key": "github", "name": "GitHub", "env": ["GITHUB_TOKEN", "AI_OS_GITHUB_REPO"],
        "status": "ok" if token else "missing",
        "detail": f"token set — repo {repo}" if token else "GITHUB_TOKEN is not set",
    }


CHECKS = [check_telegram, check_sheets, check_drive, check_docs, check_calendar, check_github]


# ---------------------------------------------------------------- live probes
def _sa_creds(scopes):
    from google.oauth2 import service_account
    info = google_credentials.service_account_info()
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)


def _google_build(api, version, scopes):
    from googleapiclient.discovery import build
    return build(api, version, credentials=_sa_creds(scopes), cache_discovery=False)


def _probe_telegram():
    from . import telegram_live
    return telegram_live.doctor()  # noqa: needs TELEGRAM_BOT_TOKEN in env before run


def _probe_github():
    from . import github_live
    return github_live.doctor()


def _probe_sheets():
    svc = _google_build("sheets", "v4", [SHEETS_READONLY])
    meta = svc.spreadsheets().get(
        spreadsheetId=_env("GOOGLE_SHEET_ID"), fields="properties.title,sheets.properties.title"
    ).execute()
    tabs = [s.get("properties", {}).get("title", "?") for s in meta.get("sheets", [])]
    return {"title": meta.get("properties", {}).get("title", ""), "tabs": len(tabs)}


def _probe_drive():
    svc = _google_build("drive", "v3", [DRIVE_READONLY])
    folder = svc.files().get(
        fileId=_env("GOOGLE_DRIVE_FOLDER_ID"), fields="id,name,mimeType", supportsAllDrives=True
    ).execute()
    return {"folder": folder.get("name", ""), "mimeType": folder.get("mimeType", "")}


def _probe_docs():
    from . import google_docs_service
    return google_docs_service.doctor()


def _probe_calendar():
    svc = _google_build("calendar", "v3", [CALENDAR_SCOPE])
    cal = svc.calendars().get(calendarId=_env("GOOGLE_CALENDAR_ID")).execute()
    return {"summary": cal.get("summary", ""), "timeZone": cal.get("timeZone", "")}


PROBES = {
    "telegram": _probe_telegram,
    "sheets": _probe_sheets,
    "drive": _probe_drive,
    "docs": _probe_docs,
    "calendar": _probe_calendar,
    "github": _probe_github,
}

STATUS_ICON = {"ok": "✅", "partial": "⚠️", "missing": "❌", "invalid": "❌"}


def run(live: bool = False) -> list:
    results = []
    for check in CHECKS:
        row = check()
        if live and row["status"] == "ok":
            probe = PROBES.get(row["key"])
            try:
                row["live"] = {"ok": True, "result": probe()}
            except Exception as exc:
                row["live"] = {"ok": False, "error": str(exc)[:400]}
        results.append(row)
    return results


def render(results, live: bool = False) -> str:
    lines = ["🔗 Connection Status — Abdulrahman AI OS", "─" * 46]
    for row in results:
        icon = STATUS_ICON.get(row["status"], "❓")
        line = f"{icon} {row['name']:<16} {row['status']} — {row['detail']}"
        if live and "live" in row:
            probe = row["live"]
            line += "  |  live: " + (
                "OK " + json.dumps(probe["result"], ensure_ascii=False) if probe["ok"]
                else f"FAIL {probe['error']}"
            )
        lines.append(line)
    pending = [r for r in results if r["status"] != "ok"]
    if pending:
        lines.append("")
        lines.append("Next steps (priority: " + " → ".join(PRIORITY_ORDER) + "):")
        for key in PRIORITY_ORDER + ["sheets", "drive", "telegram"]:
            row = next((r for r in results if r["key"] == key and r["status"] != "ok"), None)
            if row:
                lines.append(f"  • {row['name']}: python3 -m connectors.connection_setup --guide {key}")
    else:
        lines.append("")
        lines.append("🎉 All integrations configured. Run with --live to verify against the APIs.")
    return "\n".join(lines)


def main(argv):
    live = "--live" in argv
    as_json = "--json" in argv
    if "--guide" in argv:
        idx = argv.index("--guide")
        key = argv[idx + 1] if idx + 1 < len(argv) else ""
        steps = GUIDES.get(key)
        if not steps:
            print("guides: " + ", ".join(GUIDES))
            return 1
        print(f"📘 {key} — setup steps")
        for n, step in enumerate(steps, 1):
            print(f"  {n}. {step}")
        return 0
    results = run(live=live)
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render(results, live=live))
    return 0 if all(r["status"] == "ok" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

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
    "gemini": [
        "console.cloud.google.com → enable the Gemini API for the selected project.",
        "Create a Gemini API key and set GEMINI_API_KEY in Railway — never in chat or git.",
        "Set GEMINI_MODEL (default: google/gemini-3.7-flash) if a different enabled model is required.",
        "Verify: python3 -m connectors.connection_setup --live.",
    ],
    "kimi": [
        "platform.moonshot.ai → Console → API Keys (international). China: platform.moonshot.cn.",
        "Create a key and set KIMI_API_KEY in Railway — never in chat or git. MOONSHOT_API_KEY is also accepted.",
        "Optional: KIMI_MODEL (default kimi-k2.5), KIMI_BASE_URL (default https://api.moonshot.ai/v1).",
        "Keep AI_MODEL_PROVIDER=gemini to use Kimi only after Gemini's ~20 questions/day quota.",
        "Or set AI_MODEL_PROVIDER=kimi to send ordinary questions to Kimi immediately.",
        "Clinical traffic stays on Gemini unless you explicitly set AI_CLINICAL_PROVIDER=kimi.",
        "Verify: python3 -m connectors.connection_setup --live  or Telegram /kimi_test.",
    ],
    "buffer": [
        "publish.buffer.com/settings/api → create a personal API key.",
        "Set BUFFER_API_KEY locally / in the deployment variables — never in chat or git.",
        "Images must be pre-hosted on a public URL (e.g. assets/ + raw.githubusercontent.com).",
        "List channels: python3 -m connectors.buffer_publisher --list",
        "Full walkthrough: docs/buffer-setup.md",
    ],
    "videosearch": [
        "Works with zero config via DuckDuckGo (read-only verified YouTube watch URLs).",
        "Optional, more reliable: console.cloud.google.com → enable \"YouTube Data API v3\".",
        "Credentials → Create Credentials → API key → restrict it to YouTube Data API v3.",
        "Set YOUTUBE_API_KEY locally / in the deployment variables — never in chat or git.",
        "Verify: python3 -m connectors.web_search --check",
        "Bot usage: /youtube كلمات البحث — or just ask for video links in any message.",
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


def check_gemini(env=None) -> dict:
    env = env if env is not None else _env
    key = env("GEMINI_API_KEY")
    model = env("GEMINI_MODEL") or env("AI_GOOGLE_MODEL") or "google/gemini-3.7-flash"
    return {
        "key": "gemini", "name": "Gemini API",
        "env": ["GEMINI_API_KEY", "GEMINI_MODEL"],
        "status": "ok" if key else "missing",
        "detail": f"API key set — model {model}" if key else "GEMINI_API_KEY is not set",
    }


def check_kimi(env=None) -> dict:
    env = env if env is not None else _env
    key = env("KIMI_API_KEY") or env("MOONSHOT_API_KEY")
    model = env("KIMI_MODEL") or "kimi-k2.5"
    base = env("KIMI_BASE_URL") or "https://api.moonshot.ai/v1"
    if key:
        status, detail = "ok", f"API key set — model {model} @ {base}"
    else:
        status, detail = "optional", (
            "KIMI_API_KEY not set — optional overflow after Gemini's ~20 questions/day"
        )
    return {
        "key": "kimi", "name": "Kimi API",
        "env": ["KIMI_API_KEY", "KIMI_MODEL", "KIMI_BASE_URL"],
        "status": status, "detail": detail,
    }


def check_buffer(env=None) -> dict:
    env = env if env is not None else _env
    key = env("BUFFER_API_KEY")
    return {
        "key": "buffer", "name": "Buffer Publisher", "env": ["BUFFER_API_KEY"],
        "status": "ok" if key else "missing",
        "detail": "API key set — social scheduling ready"
        if key
        else "BUFFER_API_KEY is not set (publish.buffer.com/settings/api) — see docs/buffer-setup.md",
    }


CHECKS = [check_telegram, check_sheets, check_drive, check_docs, check_calendar, check_github,
          check_gemini, check_kimi, check_buffer]


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


def _probe_gemini():
    from . import model_gateway
    return model_gateway.probe_gemini()


def _probe_kimi():
    from . import model_gateway
    return model_gateway.probe_kimi()


PROBES = {
    "telegram": _probe_telegram,
    "sheets": _probe_sheets,
    "drive": _probe_drive,
    "docs": _probe_docs,
    "calendar": _probe_calendar,
    "github": _probe_github,
    "gemini": _probe_gemini,
    "kimi": _probe_kimi,
}

STATUS_ICON = {"ok": "✅", "partial": "⚠️", "missing": "❌", "invalid": "❌", "optional": "○"}


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
    pending = [r for r in results if r["status"] not in {"ok", "optional"}]
    if pending:
        lines.append("")
        lines.append("Next steps (priority: " + " → ".join(PRIORITY_ORDER) + "):")
        for key in PRIORITY_ORDER + ["sheets", "drive", "telegram", "gemini", "buffer"]:
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
    return 0 if all(r["status"] in {"ok", "optional"} for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

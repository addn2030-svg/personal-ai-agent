#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live diagnostic for the Google Calendar production path (service account).

Mirrors EXACTLY what the deployed bot does in connectors/calendar_actions.py:
GOOGLE_(CALENDAR_)SERVICE_ACCOUNT_JSON + GOOGLE_CALENDAR_ID -> list_events().

Usage (Railway parity — same variable names the service uses):
  export GOOGLE_SERVICE_ACCOUNT_JSON='<inline json | base64 | /path/to/key.json>'
  export GOOGLE_CALENDAR_ID='xxxx@group.calendar.google.com'
  python3 scripts/diagnose_calendar.py            # read-only test
  python3 scripts/diagnose_calendar.py --write-test   # + create/delete a 5-min event

Never prints secret values — only metadata (project id, client email).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors import google_credentials  # noqa: E402

PASS, FAIL, WARN, INFO = "✅", "❌", "⚠️ ", "ℹ️ "
WRITE_TEST = "--write-test" in sys.argv


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(2, 60 - len(title)))


def explain_http_error(exc: Exception, project_id: str, client_email: str) -> None:
    """Translate Google's raw error into the exact fix."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    content = str(getattr(exc, "content", b"") or "")[:600]
    msg = str(exc)
    print(f"{FAIL} Google API error: HTTP {status} — {content or msg}")
    text = (content + " " + msg).lower()
    if status == 404 or "not found" in text:
        print(f"{INFO} Meaning: the calendar is NOT visible to the service account.")
        print(f"   Fix 1: Google Calendar → ⚙️ Settings → your calendar → 'Share with specific people'")
        print(f"          → add {client_email} → 'Make changes to events'.")
        print(f"   Fix 2: check GOOGLE_CALENDAR_ID (Settings → 'Integrate calendar'), and do not use 'primary'.")
    elif status == 403 and ("has not been used" in text or "accessnotconfigured" in text or "disabled" in text):
        print(f"{INFO} Meaning: Google Calendar API is NOT enabled in project '{project_id}'.")
        print(f"   Enabling it in any other project does nothing — the API must be on in the")
        print(f"   project that OWNS this service account:")
        print(f"   https://console.cloud.google.com/apis/library/calendar-json.googleapis.com?project={project_id}")
    elif status == 403 or "insufficient" in text:
        print(f"{INFO} Meaning: permission level too low on the shared calendar.")
        print(f"   Fix: re-share with {client_email} at 'Make changes to events' level.")
    elif status == 401 or "invalid_grant" in text or "invalid jwt" in text:
        print(f"{INFO} Meaning: the key was rejected (revoked, rotated, or malformed in the env var).")
        print(f"   Fix: Service Accounts → Keys → create a NEW JSON key → replace the Railway variable.")
    else:
        print(f"{INFO} Unclassified — paste this output back and I'll decode it.")


def main() -> int:
    failures = 0

    step("1/6  Environment variables")
    raw_cal = os.environ.get("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON", "").strip()
    raw_gen = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    cal_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"
    tz = os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh")
    print(f"{'✅' if raw_cal or raw_gen else '❌'} service-account JSON present: "
          f"GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON={'set' if raw_cal else '—'} "
          f"GOOGLE_SERVICE_ACCOUNT_JSON={'set' if raw_gen else '—'}")
    print(f"{'✅' if cal_id != 'primary' else '❌'} GOOGLE_CALENDAR_ID = {cal_id!r}")
    print(f"{INFO} MANAGER_TIMEZONE = {tz}")
    if not (raw_cal or raw_gen):
        print(f"{FAIL} no credentials set — nothing to test"); return 1

    step("2/6  Parse credential JSON (same parser as production)")
    info = google_credentials.service_account_info(raw_cal or raw_gen)
    if not info:
        print(f"{FAIL} present but INVALID — not parseable as a service-account key.")
        print(f"   Common cause: the JSON got mangled when pasted into the env var")
        print(f"   (lost newlines/quotes). Fix: store it base64-encoded — the parser auto-detects:")
        print(f"   base64 -w0 key.json   →   paste that as the variable value.")
        return 1
    project_id = info.get("project_id", "?")
    client_email = info.get("client_email", "?")
    print(f"{PASS} valid service-account key")
    print(f"   project_id   : {project_id}")
    print(f"   client_email : {client_email}")
    print(f"{WARN} The Calendar API must be enabled in project '{project_id}' specifically —")
    print(f"   enabling it in a different project is the #1 silent cause of failure.")

    step("3/6  Connector health (calendar_auth_status)")
    from connectors.calendar_actions import calendar_auth_status
    status = calendar_auth_status()
    for k, v in status.items():
        print(f"   {k}: {v}")
    if cal_id == "primary":
        failures += 1
        print(f"{FAIL} calendar_id_mode='primary' → production falls back to the LOCAL OAuth")
        print(f"   path (secrets/google-oauth-client.json) which does not exist on Railway.")
        print(f"   Fix: set GOOGLE_CALENDAR_ID to the real calendar id.")

    step("4/6  Build Calendar API client")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/calendar"])
        cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
        print(f"{PASS} client built")
    except Exception as exc:
        print(f"{FAIL} could not build client: {exc}")
        return 1

    step("5/6  Can the service account SEE the calendar?")
    visible = cal.calendarList().list(maxResults=5).execute().get("items", [])
    print(f"{INFO} calendars in the service account's own list: {len(visible)} (0 is NORMAL — read on)")
    for c in visible:
        print(f"   • {c.get('summary')} ({c.get('id')})")
    if cal_id != "primary":
        try:
            meta = cal.calendars().get(calendarId=cal_id).execute()
            print(f"{PASS} calendar '{meta.get('summary', cal_id)}' is visible → sharing is correct")
        except Exception as exc:
            failures += 1
            explain_http_error(exc, project_id, client_email)

    step("6/6  Read events like the bot's brief does (list_events, 7 days)")
    try:
        from connectors.calendar_actions import list_events
        events = list_events(days_forward=7, max_results=10)
        print(f"{PASS} {len(events)} event(s) in the next 7 days:")
        for e in events[:10]:
            print(f"   • {e['title']} | {e['start']}")
        if not events:
            print(f"{INFO} empty window is fine IF your calendar has nothing in the next 7 days.")
    except Exception as exc:
        failures += 1
        explain_http_error(exc, project_id, client_email)

    if WRITE_TEST and not failures:
        step("extra  Write test — create & delete a 5-minute event")
        try:
            now = dt.datetime.now().astimezone()
            body = {
                "summary": "AI OS connectivity test (auto-deleted)",
                "start": {"dateTime": (now + dt.timedelta(minutes=10)).isoformat(), "timeZone": tz},
                "end": {"dateTime": (now + dt.timedelta(minutes=15)).isoformat(), "timeZone": tz},
            }
            created = cal.events().insert(calendarId=cal_id, body=body).execute()
            cal.events().delete(calendarId=cal_id, eventId=created["id"]).execute()
            print(f"{PASS} write + delete succeeded → 'Make changes to events' permission confirmed")
        except Exception as exc:
            failures += 1
            explain_http_error(exc, project_id, client_email)

    print("\n" + "=" * 62)
    print(f"{'❌ DIAGNOSIS: FAILING — see the ❌ lines above' if failures else '✅ DIAGNOSIS: Calendar path is HEALTHY end-to-end'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

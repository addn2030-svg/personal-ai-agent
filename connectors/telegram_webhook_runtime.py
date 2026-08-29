# -*- coding: utf-8 -*-
"""Production Telegram webhook runtime with direct-first Google Sheets writes.

If a valid Google service account is configured, writes go directly to the
Sheets API. The Apps Script webhook remains a fallback only.
"""
from __future__ import annotations

import time

from connectors import telegram_webhook as webhook
from connectors import google_credentials

bot = webhook.bot
_fallback_append = bot._append
_direct_service = None


def _direct_ready() -> bool:
    return bool(bot.GOOGLE_SHEET_ID and google_credentials.service_account_info())


def _service():
    global _direct_service
    if _direct_service is not None:
        return _direct_service
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing or invalid")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _direct_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _direct_service


def _direct_append(tab: str, row: list):
    return _service().spreadsheets().values().append(
        spreadsheetId=bot.GOOGLE_SHEET_ID,
        range=f"'{tab}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def _append_direct_first(tab: str, row: list):
    direct_error = None
    if _direct_ready():
        for attempt, delay in enumerate((0, 1, 2), start=1):
            if delay:
                time.sleep(delay)
            try:
                _direct_append(tab, row)
                return
            except Exception as exc:  # connector boundary
                direct_error = exc
                print(
                    f"Sheets direct write attempt {attempt}/3 failed for {tab}: {str(exc)[:180]}",
                    flush=True,
                )

    try:
        return _fallback_append(tab, row)
    except Exception as fallback_error:
        if direct_error is not None:
            raise RuntimeError(
                "Google Sheets direct write failed; Apps Script fallback also failed: "
                + str(fallback_error)[:220]
            ) from fallback_error
        raise


bot._append = _append_direct_first


def run():
    state = google_credentials.status()
    print(
        "Sheets production route: "
        + ("direct-first" if _direct_ready() else "Apps-Script-only")
        + f" | service_account={state.get('source')} valid={state.get('valid')}",
        flush=True,
    )
    webhook.run()


if __name__ == "__main__":
    run()

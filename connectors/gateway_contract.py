# -*- coding: utf-8 -*-
"""Canonical Google Sheets Apps Script gateway contract and live handshake."""
from __future__ import annotations

import json
import os
import urllib.request

EXPECTED_ACTIONS = frozenset({
    "append",
    "metadata",
    "snapshot",
    "search",
    "upsert_metrics",
    "update",
    "ping",
})


def ping_live(url: str | None = None, secret: str | None = None, timeout: int = 30):
    url = (url or os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "")).strip()
    secret = (secret or os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "")).strip()
    if not url or not secret:
        raise RuntimeError("GOOGLE_SHEETS_WEBHOOK_URL/SECRET are required for live handshake")
    payload = json.dumps({"secret": secret, "action": "ping"}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = json.loads(urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Sheets gateway ping failed: " + str(result.get("error", "unknown")))
    actions = frozenset(map(str, result.get("actions", [])))
    if actions != EXPECTED_ACTIONS:
        missing = sorted(EXPECTED_ACTIONS - actions)
        extra = sorted(actions - EXPECTED_ACTIONS)
        raise RuntimeError(f"live gateway contract drift: missing={missing} extra={extra}")
    return result

# -*- coding: utf-8 -*-
"""Safe parsing helpers for Google service-account configuration.

Accepts the Railway GOOGLE_SERVICE_ACCOUNT_JSON value as normal JSON,
double-encoded JSON, or base64-encoded JSON. Never logs or returns secrets in
status helpers.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any


def _raw_value() -> str:
    return os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()


def _decode_json_candidate(value: str) -> Any:
    current: Any = value
    for _ in range(3):
        if not isinstance(current, str):
            return current
        current = json.loads(current.strip())
    return current


def service_account_info(raw: str | None = None) -> dict | None:
    """Return validated service-account info, or None without exposing secrets."""
    value = _raw_value() if raw is None else str(raw or "").strip()
    if not value:
        return None

    candidates = [value]
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8").strip()
        if decoded and decoded != value:
            candidates.append(decoded)
    except Exception:
        pass

    for candidate in candidates:
        try:
            data = _decode_json_candidate(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("type") != "service_account":
            continue
        if not data.get("client_email") or not data.get("private_key") or not data.get("token_uri"):
            continue
        clean = dict(data)
        key = str(clean.get("private_key", ""))
        if "\\n" in key and "\n" not in key:
            clean["private_key"] = key.replace("\\n", "\n")
        return clean
    return None


def status() -> dict:
    raw = _raw_value()
    info = service_account_info(raw)
    return {
        "present": bool(raw),
        "valid": bool(info),
        "has_client_email": bool(info and info.get("client_email")),
        "has_private_key": bool(info and info.get("private_key")),
        "has_project_id": bool(info and info.get("project_id")),
    }

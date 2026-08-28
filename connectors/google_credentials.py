# -*- coding: utf-8 -*-
"""Safe parsing helpers for Google service-account configuration.

Accepts the Railway GOOGLE_SERVICE_ACCOUNT_JSON value as normal JSON,
double-encoded JSON, base64-encoded JSON, or a path to a mounted JSON file.
Never logs or returns credential contents in status helpers.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

MAX_CREDENTIAL_FILE_BYTES = 128 * 1024


def _raw_value() -> str:
    return os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()


def _decode_json_candidate(value: str) -> Any:
    current: Any = value
    for _ in range(3):
        if not isinstance(current, str):
            return current
        current = json.loads(current.strip())
    return current


def _file_payload(value: str) -> str | None:
    """Read a referenced local credential file without exposing its path/content."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file://"):
        text = text[7:]
    if not text.lower().endswith(".json"):
        return None
    try:
        path = Path(text).expanduser()
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size <= 0 or size > MAX_CREDENTIAL_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _validated_info(data: Any) -> dict | None:
    if not isinstance(data, dict):
        return None
    if data.get("type") != "service_account":
        return None
    if not data.get("client_email") or not data.get("private_key") or not data.get("token_uri"):
        return None
    clean = dict(data)
    key = str(clean.get("private_key", ""))
    if "\\n" in key and "\n" not in key:
        clean["private_key"] = key.replace("\\n", "\n")
    return clean


def service_account_info(raw: str | None = None) -> dict | None:
    """Return validated service-account info, or None without exposing secrets."""
    value = _raw_value() if raw is None else str(raw or "").strip()
    if not value:
        return None

    candidates = [value]
    file_payload = _file_payload(value)
    if file_payload:
        candidates.insert(0, file_payload)

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
        info = _validated_info(data)
        if info:
            return info
    return None


def source(raw: str | None = None) -> str:
    """Return a non-secret credential source label for diagnostics."""
    value = _raw_value() if raw is None else str(raw or "").strip()
    if not value:
        return "missing"
    if _file_payload(value):
        return "file"
    if service_account_info(value):
        return "inline"
    if value.lower().endswith(".json") or value.startswith("file://"):
        return "file-missing-or-invalid"
    return "invalid"


def status() -> dict:
    raw = _raw_value()
    info = service_account_info(raw)
    return {
        "present": bool(raw),
        "valid": bool(info),
        "source": source(raw),
        "has_client_email": bool(info and info.get("client_email")),
        "has_private_key": bool(info and info.get("private_key")),
        "has_project_id": bool(info and info.get("project_id")),
    }

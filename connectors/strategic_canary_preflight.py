# -*- coding: utf-8 -*-
"""Fail-closed preflight for a future read-only Strategic Creator canary.

This module does not start Telegram, call a model, or write to any store. Current
human-review gates intentionally keep the canary blocked.
"""
from __future__ import annotations

import json
import os

from connectors import shadow_acceptance_sheet

REQUIRED_MODE = "READ_ONLY_SHADOW"


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


def local_safety_checks() -> dict:
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    return {
        "strategic_feature_enabled": _flag("AI_STRATEGIC_CREATOR_ENABLED"),
        "read_only_shadow_mode": (
            os.environ.get("STRATEGIC_CANARY_MODE", "").strip()
            == REQUIRED_MODE
        ),
        "dev_sheet_configured": bool(dev_id),
        "dev_target_differs_from_live": bool(dev_id and (not live_id or dev_id != live_id)),
        "telegram_polling_disabled": not _flag("AI_OS_ALLOW_POLLING"),
        "possibility_writes_disabled": not _flag("POSSIBILITY_DEV_WRITE_ENABLED"),
        "acceptance_writes_disabled": not _flag("SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED"),
    }


def preflight(*, report_reader=None) -> dict:
    checks = local_safety_checks()
    reader = report_reader or shadow_acceptance_sheet.read_acceptance_report
    report = None
    source_error = ""
    if all(checks.values()):
        try:
            report = reader()
        except Exception as exc:
            source_error = str(exc)[:240]
    else:
        source_error = "local safety checks failed; DEV Sheet was not read"

    acceptance_decision = (
        report.get("decision") if isinstance(report, dict) else "UNAVAILABLE"
    )
    checks["human_acceptance_gate"] = (
        acceptance_decision == "ELIGIBLE_FOR_MANUAL_CANARY_REVIEW"
    )
    ready = all(checks.values())
    return {
        "mode": REQUIRED_MODE,
        "ready": ready,
        "decision": "READY_FOR_MANUAL_START" if ready else "BLOCKED",
        "checks": checks,
        "acceptance_decision": acceptance_decision,
        "source_error": source_error,
        "external_model_calls": 0,
        "telegram_started": False,
        "writes_enabled": False,
        "automatic_start": False,
    }


def assert_ready(*, report_reader=None) -> dict:
    result = preflight(report_reader=report_reader)
    if not result["ready"]:
        failed = [name for name, passed in result["checks"].items() if not passed]
        raise RuntimeError("Strategic canary blocked: " + ", ".join(failed))
    return result


def main() -> int:
    result = preflight()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

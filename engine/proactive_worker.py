# -*- coding: utf-8 -*-
"""Safe delivery worker for the proactive Chief of Staff Pilot.

The worker is disabled unless PROACTIVE_ENABLED=1. Delivery also fails closed
without TELEGRAM_ALLOWED_CHAT_ID. Use --once --dry-run for DEV inspection.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import sheet_intelligence
from connectors import telegram_bot_legacy as bot
from engine import proactive_controller as controller
from engine.store import Store

INTERVAL_SECONDS = max(30, int(os.environ.get("PROACTIVE_INTERVAL_SECONDS", "60")))


def _enabled() -> bool:
    return os.environ.get("PROACTIVE_ENABLED", "0").strip() == "1"


def _dry_run() -> bool:
    return os.environ.get("PROACTIVE_DRY_RUN", "1").strip() == "1"


def _owner_chat_id() -> int:
    value = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if not value:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID is required for proactive delivery")
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID must be numeric") from exc


def _append_followup(alert: dict, event: str, response: str = ""):
    """Log before delivery through the Gateway's append-only path only."""
    if not sheet_intelligence._webhook_ready():
        raise RuntimeError("Sheets webhook is required for FollowUp_Log append")
    row = controller.followup_row(alert, event, response)
    request_id = f"proactive-{alert['alert_id']}-{event.lower()}"
    return sheet_intelligence._webhook(
        "append",
        tab="FollowUp_Log",
        row=row,
        request_id=request_id,
    )


def _contextual_state(store: Store) -> Store:
    """Keep the source read deterministic; future adapters can add Sheets reads."""
    return store


def _load_external_evidence() -> list[dict]:
    """Read only non-clinical signal labels from connected Sheets.

    The actual row text is intentionally not copied into a Telegram alert. This
    keeps the proactive path useful for Projects/OKRs/Waiting_For while avoiding
    accidental clinical or relationship-detail disclosure.
    """
    try:
        snapshot = sheet_intelligence.snapshot(max_rows=80, max_cols=16)
    except Exception:
        return []
    excluded = {
        "Calc_Data", "مدخلات الوكيل", "محادثات الوكيل", "حالة الوكيل",
        "FollowUp_Log", "Telegram_Log", "Agent_Log", "Approval_Log", "Decision_Log",
    }
    signals = ("okr", "objective", "هدف", "تفويض", "delegat", "قرار", "decision", "blocker", "عائق", "waiting")
    clinical = ("patient", "مريض", "diagnosis", "تشخيص", "clinical", "سريري", "mrn", "medical record")
    evidence = []
    try:
        from engine.books_context import extract_books
        for book in extract_books(snapshot or {}):
            status = str(book.get("status") or "").strip().lower()
            if status in {"تم", "منجز", "مكتمل", "انتهى", "منجزة"}:
                continue
            title = str(book.get("title") or "").strip()
            if title:
                evidence.append({
                    "source": f"Google Sheets:{book.get('tab', 'المصادر والتعلم العلمي')}",
                    "date": "غير مؤرخ",
                    "signal": f"كتاب مسجل للمراجعة: {title[:160]}",
                })
                if len(evidence) >= 5:
                    return evidence
    except Exception:
        pass

    for tab, rows in (snapshot or {}).items():
        if tab in excluded:
            continue
        for row_number, row in enumerate(rows or [], 1):
            text = " | ".join(str(value) for value in row)
            lowered = text.lower()
            if any(term in lowered for term in clinical):
                continue
            matched = next((term for term in signals if term in lowered), None)
            if not matched:
                continue
            date_match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
            evidence.append({
                "source": f"Google Sheets:{tab} row {row_number}",
                "date": date_match.group(0) if date_match else "غير مؤرخ",
                "signal": f"إشارة إدارية من نوع {matched} (تمت حماية محتوى الصف)",
            })
            if len(evidence) >= 5:
                return evidence
    return evidence


def dispatch_alert(alert: dict, *, dry_run: bool | None = None, store: Store | None = None) -> str:
    store = store or Store()
    dry_run = _dry_run() if dry_run is None else bool(dry_run)

    # Dry Run is side-effect free: no Telegram call, no Gateway append, and no
    # local claim. This is the default until T3 approval.
    if dry_run:
        return "dry_run"

    config = controller.get_config(store)
    if not (config.get("enabled", False) and config.get("t3_approved", False)):
        return "state_disabled_or_unapproved"

    if not controller.claim_alert(alert, store=store):
        return "duplicate_or_budget"

    try:
        # A proposal is recorded before any Telegram send. If this fails, no send
        # occurs and the alert is marked LOG_FAILED.
        _append_followup(alert, "PROPOSED")
    except Exception as exc:
        controller.mark_alert(alert["alert_id"], "LOG_FAILED", str(exc), store=store)
        return "log_failed"

    try:
        chat_id = _owner_chat_id()
        bot.send(chat_id, controller.format_alert(alert))
        controller.mark_alert(alert["alert_id"], "SENT", "telegram_owner", store=store)
        try:
            _append_followup(alert, "SENT")
        except Exception as exc:
            controller.mark_alert(alert["alert_id"], "SENT_LOG_FAILED", str(exc), store=store)
        return "sent"
    except Exception as exc:
        controller.mark_alert(alert["alert_id"], "DELIVERY_FAILED", str(exc), store=store)
        try:
            _append_followup(alert, "DELIVERY_FAILED", str(exc)[:220])
        except Exception:
            pass
        return "delivery_failed"


def record_owner_response(alert_id: str, response: str, *, store: Store | None = None) -> dict:
    store = store or Store()
    result = controller.record_response(alert_id, response, store=store)
    alert = result["alert"]
    _append_followup(alert, "RESPONSE", result["response"]["response"])
    return result


def run_once(*, dry_run: bool | None = None, include_context: bool = False,
             now=None, store: Store | None = None) -> dict:
    store = store or Store()
    if not _enabled() and dry_run is not True:
        return {"status": "disabled", "candidates": 0, "delivered": 0, "results": []}
    config = controller.get_config(store, now)
    if dry_run is not True and not (config.get("enabled", False) and config.get("t3_approved", False)):
        return {"status": "state_disabled_or_unapproved", "candidates": 0, "delivered": 0, "results": []}
    external_evidence = _load_external_evidence() if include_context else []
    candidates = controller.collect(
        now=now,
        store=store,
        include_context=include_context,
        external_evidence=external_evidence,
    )
    results = [dispatch_alert(alert, dry_run=dry_run, store=store) for alert in candidates]
    return {
        "status": "dry_run" if (dry_run is True or _dry_run()) else "enabled",
        "candidates": len(candidates),
        "delivered": sum(result == "sent" for result in results),
        "results": results,
    }


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="never send Telegram; still exercise the controller")
    parser.add_argument("--context", action="store_true", help="include one evidence-backed historical suggestion")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    dry_run = True if args.dry_run else None
    if args.once:
        result = run_once(dry_run=dry_run, include_context=args.context)
        print(f"Proactive worker: {result}", flush=True)
        return 0
    if not _enabled():
        print("Proactive worker disabled: set PROACTIVE_ENABLED=1 only after DEV review", flush=True)
        return 0
    while True:
        result = run_once(dry_run=dry_run, include_context=True)
        print(f"Proactive worker cycle: {result}", flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())

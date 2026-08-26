# -*- coding: utf-8 -*-
"""Normalize new inputs into one provenance-aware, transaction-safe inbox queue."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

PRIVATE_PLACEHOLDER = "[REDACTED_FROM_PERSONAL_OS]"
ALLOWED_CLASSIFICATIONS = {
    "TASK", "REQUEST", "DECISION", "WAITING_FOR", "FACT", "DOCUMENT", "IDEA",
    "CLINICAL_PRIVATE", "APPOINTMENT", "IGNORE",
}


def add(source, content, kind="TEXT", source_ref="", sensitive=False, metadata=None):
    raw = f"{source}|{source_ref}|{content}".encode("utf-8")
    iid = "IN-" + hashlib.sha256(raw).hexdigest()[:10].upper()
    persisted_content = PRIVATE_PLACEHOLDER if sensitive else content
    created = {"value": False}

    def mutate(S):
        rows = S.setdefault("unified_inbox", [])
        if any(item.get("id") == iid for item in rows):
            return False, iid
        rows.append({
            "id": iid,
            "captured_at": dt.datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "source_ref": source_ref,
            "kind": kind,
            "content": persisted_content,
            "sensitive": bool(sensitive),
            "metadata": metadata or {},
            "status": "NEW",
            "classification": None,
            "next_action": None,
        })
        created["value"] = True
        return True, iid

    result = Store().transaction(mutate, "unified_inbox_add", item=iid, source=source)
    if created["value"]:
        log_event("UNIFIED_INBOX_CAPTURED", item=iid, source=source)
        print(f"📥 {iid} captured from {source}")
    else:
        print(f"↩️ duplicate ignored: {iid}")
    return result


def classify(iid, classification, next_action=""):
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise ValueError("invalid classification")

    def mutate(S):
        rec = next((item for item in S.setdefault("unified_inbox", []) if item.get("id") == iid), None)
        if not rec:
            raise ValueError("inbox item not found")
        status = "NEEDS_CONFIRMATION" if classification == "APPOINTMENT" else "CLASSIFIED"
        rec.update(
            classification=classification,
            next_action=next_action or ("Confirm appointment details" if classification == "APPOINTMENT" else ""),
            status=status,
            classified_at=dt.datetime.now().isoformat(timespec="seconds"),
        )
        if classification == "CLINICAL_PRIVATE":
            rec["content"] = PRIVATE_PLACEHOLDER
            rec["sensitive"] = True
        return True, status

    status = Store().transaction(
        mutate,
        "unified_inbox_classify",
        item=iid,
        classification=classification,
    )
    log_event("UNIFIED_INBOX_CLASSIFIED", item=iid, classification=classification, status=status)
    print(f"✅ {iid} → {classification} ({status})")
    return status


def listing():
    S = Store().rows_all()
    rows = [item for item in S.get("unified_inbox", []) if item.get("status") == "NEW"]
    for item in rows[-30:]:
        print(item["id"], item["source"], item["kind"], str(item["content"])[:100])
    print(f"NEW={len(rows)}")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "add":
            add(sys.argv[2], " ".join(sys.argv[3:]))
        elif len(sys.argv) > 3 and sys.argv[1] == "classify":
            classify(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        else:
            listing()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2)

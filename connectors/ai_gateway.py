# -*- coding: utf-8 -*-
"""Secure ingestion gateway for external AI advisers.

External AIs may submit observations, recommendations and status updates, but they
never write operational project/task/calendar state directly. Every accepted
message is normalized into Unified Inbox, attributed to a source, deduplicated by
(source,event_id), and then reviewed by the Manager.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import threading
from typing import Mapping

from engine.store import Store, log_event
from engine import unified_inbox

UPDATE_PATH = os.environ.get("AI_GATEWAY_UPDATE_PATH", "/api/ai/update").strip() or "/api/ai/update"
HEALTH_PATH = os.environ.get("AI_GATEWAY_HEALTH_PATH", "/api/ai/health").strip() or "/api/ai/health"
MAX_SUMMARY_CHARS = 4000
MAX_EVIDENCE_ITEMS = 10
PRIVATE_PLACEHOLDER = "[REDACTED_FROM_PERSONAL_OS]"

ALLOWED_TYPES = {
    "TASK", "REQUEST", "DECISION", "WAITING_FOR", "FACT", "DOCUMENT", "IDEA",
    "APPOINTMENT", "RISK", "OPPORTUNITY", "BLOCKER", "PROJECT_UPDATE",
    "STATUS_CHANGE", "RECOMMENDATION", "CONTRADICTION", "EXTERNAL_AI_RESULT",
}
ALLOWED_URGENCY = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
WAKE_TYPES = {"RISK", "BLOCKER", "CONTRADICTION", "STATUS_CHANGE", "APPOINTMENT"}

DEFAULT_SOURCE_PROFILES = {
    "chatgpt": {"role": "executive_reasoning", "trust_level": 2},
    "claude": {"role": "architecture_and_code_review", "trust_level": 2},
    "gemini": {"role": "google_ecosystem_and_research", "trust_level": 2},
    "kimi": {"role": "research_adviser", "trust_level": 1},
    "deepseek": {"role": "technical_adviser", "trust_level": 1},
}


def _keys() -> dict[str, str]:
    result: dict[str, str] = {}
    raw = os.environ.get("AI_GATEWAY_KEYS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for source, secret in parsed.items():
                    if str(secret).strip():
                        result[str(source).strip().lower()] = str(secret).strip()
        except json.JSONDecodeError:
            pass
    for source in ("CHATGPT", "CLAUDE", "GEMINI", "KIMI", "DEEPSEEK"):
        value = os.environ.get(f"AI_GATEWAY_{source}_KEY", "").strip()
        if value:
            result[source.lower()] = value
    return result


def configured_sources() -> list[str]:
    return sorted(_keys())


def authenticate(headers: Mapping[str, str]) -> str | None:
    """Return canonical source when X-AI-Source + bearer token are valid."""
    source = str(headers.get("X-AI-Source", "")).strip().lower()
    auth = str(headers.get("Authorization", "")).strip()
    if not source or not auth.lower().startswith("bearer "):
        return None
    supplied = auth[7:].strip()
    expected = _keys().get(source, "")
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        return None
    return source


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def validate_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    event_id = _text(payload.get("event_id"), 128)
    update_type = _text(payload.get("type"), 64).upper()
    summary = _text(payload.get("summary"), MAX_SUMMARY_CHARS)
    urgency = _text(payload.get("urgency") or "NORMAL", 16).upper()
    if not event_id:
        raise ValueError("event_id is required")
    if update_type not in ALLOWED_TYPES:
        raise ValueError("unsupported update type")
    if not summary:
        raise ValueError("summary is required")
    if urgency not in ALLOWED_URGENCY:
        raise ValueError("invalid urgency")

    confidence = payload.get("confidence")
    if confidence in (None, ""):
        confidence = None
    else:
        confidence = float(confidence)
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")

    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    evidence = [_text(x, 1000) for x in evidence[:MAX_EVIDENCE_ITEMS] if _text(x, 1000)]

    return {
        "event_id": event_id,
        "type": update_type,
        "summary": summary,
        "project": _text(payload.get("project"), 300),
        "confidence": confidence,
        "urgency": urgency,
        "evidence": evidence,
        "proposed_action": _text(payload.get("proposed_action"), 2000),
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "sensitive": bool(payload.get("sensitive", False)),
    }


def _touch_source(source: str, event_id: str, update_type: str, urgency: str):
    profile = DEFAULT_SOURCE_PROFILES.get(source, {"role": "external_adviser", "trust_level": 1})
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def mutate(S):
        rows = S.setdefault("ai_sources", [])
        rec = next((r for r in rows if r.get("source") == source), None)
        if rec is None:
            rec = {
                "source": source,
                "role": profile["role"],
                "trust_level": profile["trust_level"],
                "enabled": True,
                "events_received": 0,
            }
            rows.append(rec)
        rec["last_seen"] = stamp
        rec["last_event_id"] = event_id
        rec["last_type"] = update_type
        rec["last_urgency"] = urgency
        rec["events_received"] = int(rec.get("events_received", 0) or 0) + 1
        return True, dict(rec)

    return Store().transaction(mutate, "ai_source_seen", source=source, event_id=event_id)


def _wake_manager_async(reason: str):
    def worker():
        try:
            from engine.ai_manager import reactive_cycle
            reactive_cycle()
        except Exception as exc:  # noqa: BLE001 - runtime boundary
            log_event("AI_GATEWAY_MANAGER_WAKE_FAILED", reason=reason, error=str(exc)[:240])

    threading.Thread(target=worker, name="ai-gateway-manager-wake", daemon=True).start()


def ingest(source: str, payload: dict) -> dict:
    source = str(source or "").strip().lower()
    if not source:
        raise ValueError("source is required")
    clean = validate_payload(payload)

    # A sensitive update keeps only provenance/routing metadata in the Personal OS.
    # Free text, evidence, project labels and proposed actions are not persisted here.
    if clean["sensitive"]:
        metadata_project = ""
        metadata_evidence = []
        metadata_proposed_action = PRIVATE_PLACEHOLDER
        classification_action = PRIVATE_PLACEHOLDER
    else:
        metadata_project = clean["project"]
        metadata_evidence = clean["evidence"]
        metadata_proposed_action = clean["proposed_action"]
        classification_action = clean["proposed_action"]

    metadata = {
        "origin": "external_ai",
        "ai_source": source,
        "event_id": clean["event_id"],
        "update_type": clean["type"],
        "project": metadata_project,
        "confidence": clean["confidence"],
        "urgency": clean["urgency"],
        "evidence": metadata_evidence,
        "proposed_action": metadata_proposed_action,
        "requires_confirmation": clean["requires_confirmation"],
        "sensitive": clean["sensitive"],
    }
    iid, created = unified_inbox.add(
        source=f"AI:{source}",
        content=clean["summary"],
        kind="AI_UPDATE",
        source_ref=clean["event_id"],
        external_id=clean["event_id"],
        sensitive=clean["sensitive"],
        metadata=metadata,
        return_created=True,
    )
    if not created:
        return {"ok": True, "duplicate": True, "inbox_id": iid, "event_id": clean["event_id"]}

    unified_inbox.classify(iid, clean["type"], classification_action)
    source_state = _touch_source(source, clean["event_id"], clean["type"], clean["urgency"])
    log_event(
        "AI_GATEWAY_ACCEPTED",
        source=source,
        event_id=clean["event_id"],
        update_type=clean["type"],
        urgency=clean["urgency"],
        sensitive=clean["sensitive"],
        inbox_id=iid,
    )

    wake = clean["urgency"] in {"HIGH", "CRITICAL"} or clean["type"] in WAKE_TYPES
    if wake:
        _wake_manager_async(f"{source}:{clean['event_id']}")
    return {
        "ok": True,
        "duplicate": False,
        "inbox_id": iid,
        "event_id": clean["event_id"],
        "classification": clean["type"],
        "manager_wake": wake,
        "source": source_state,
    }


def health() -> dict:
    return {
        "ok": True,
        "gateway": "multi-ai-v0.5",
        "configured_sources": configured_sources(),
        "update_path": UPDATE_PATH,
    }

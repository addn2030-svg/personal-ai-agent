# -*- coding: utf-8 -*-
"""Reactive review layer for updates submitted by external AI advisers.

This module deliberately does not let outside AIs mutate tasks, projects, Calendar,
or outbound communications. It reviews attributed Unified Inbox records, escalates
high-risk items into decision requests, records explicit contradictions, and then
runs the existing deterministic Manager fast cycle.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from engine.store import Store, log_event

ESCALATE_TYPES = {"RISK", "BLOCKER", "CONTRADICTION"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _review_mutation(S):
    changed = False
    reviewed = 0
    escalated = 0
    contradictions = 0
    events = []
    inbox = S.setdefault("unified_inbox", [])
    decision_requests = S.setdefault("decision_requests", [])
    contradiction_rows = S.setdefault("contradictions", [])

    for item in inbox:
        metadata = item.get("metadata") or {}
        if metadata.get("origin") != "external_ai":
            continue
        if item.get("status") not in {"CLASSIFIED", "NEEDS_CONFIRMATION"}:
            continue

        classification = str(item.get("classification") or "EXTERNAL_AI_RESULT").upper()
        urgency = str(metadata.get("urgency") or "NORMAL").upper()
        needs_owner = (
            classification in ESCALATE_TYPES
            or urgency in {"HIGH", "CRITICAL"}
            or bool(metadata.get("requires_confirmation"))
            or classification == "APPOINTMENT"
        )

        if classification == "CONTRADICTION":
            cid = "C-AI-" + _hash(item["id"])
            if not any(c.get("id") == cid for c in contradiction_rows):
                contradiction_rows.append({
                    "id": cid,
                    "status": "OPEN",
                    "source": metadata.get("ai_source") or item.get("source"),
                    "source_item": item.get("id"),
                    "project": metadata.get("project") or "",
                    "summary": item.get("content"),
                    "evidence": metadata.get("evidence") or [],
                    "created_at": _now_iso(),
                })
                contradictions += 1
                changed = True

        if needs_owner:
            dr_id = "DR-AI-" + _hash(item["id"])
            if not any(d.get("id") == dr_id for d in decision_requests):
                source = metadata.get("ai_source") or item.get("source") or "external AI"
                project = metadata.get("project") or "غير محدد"
                proposed = metadata.get("proposed_action") or "لا يوجد إجراء مقترح"
                decision_requests.append({
                    "id": dr_id,
                    "project": project,
                    "title": f"مراجعة تحديث من {source}: {classification}",
                    "context": (
                        f"المصدر: {source}\n"
                        f"الأولوية: {urgency}\n"
                        f"الملخص: {item.get('content') or ''}\n"
                        f"الإجراء المقترح: {proposed}"
                    ),
                    "options": [
                        "تحقق ثم نفّذ الإجراء المناسب",
                        "احتفظ للمراقبة دون تنفيذ",
                        "ارفض التحديث ولا تعتمد عليه",
                    ],
                    "deadline": dt.date.today().isoformat(),
                    "status": "PENDING",
                    "created_at": dt.date.today().isoformat(),
                    "resolved_at": None,
                    "resolution": None,
                    "source_item": item.get("id"),
                    "external_source": source,
                })
                escalated += 1
                changed = True
            item["status"] = "ESCALATED"
        else:
            item["status"] = "MANAGER_REVIEWED"
        item["manager_reviewed_at"] = _now_iso()
        reviewed += 1
        changed = True
        events.append((
            "AI_MANAGER_REVIEWED",
            {
                "item": item.get("id"),
                "classification": classification,
                "urgency": urgency,
                "escalated": needs_owner,
            },
        ))

    S["decision_requests"] = decision_requests
    S["contradictions"] = contradiction_rows
    return changed, {
        "reviewed": reviewed,
        "escalated": escalated,
        "contradictions": contradictions,
        "events": events,
    }


def review_external_updates():
    result = Store().transaction(_review_mutation, "ai_manager_review")
    for event, details in result.get("events", []):
        log_event(event, **details)
    return {k: v for k, v in result.items() if k != "events"}


def reactive_cycle():
    result = review_external_updates()
    try:
        from engine.manager import fast_cycle
        result["manager_fast"] = fast_cycle()
    except Exception as exc:  # noqa: BLE001 - preserve external update even if sweep fails
        result["manager_fast_error"] = str(exc)[:240]
        log_event("AI_MANAGER_FAST_CYCLE_FAILED", error=str(exc)[:240])
    return result

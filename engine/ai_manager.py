# -*- coding: utf-8 -*-
"""Reactive review layer for updates submitted by external AI advisers.

Outside AIs never mutate tasks, projects, Calendar, or outbound communications. This
layer reviews attributed Unified Inbox records, escalates high-risk items into owner
decisions, records contradictions, and may invoke the multi-model AI Council for only
material cases under explicit daily/cycle limits.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from engine.store import Store, log_event

ESCALATE_TYPES = {"RISK", "BLOCKER", "CONTRADICTION"}
AUTO_COUNCIL_ENABLED = os.environ.get("AI_AUTO_COUNCIL_ENABLED", "1").strip() != "0"
AUTO_COUNCIL_DAILY_LIMIT = int(os.environ.get("AI_AUTO_COUNCIL_DAILY_LIMIT", "5"))
AUTO_COUNCIL_MAX_PER_CYCLE = int(os.environ.get("AI_AUTO_COUNCIL_MAX_PER_CYCLE", "1"))


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
    council_candidates = []
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

        # Automatic council is deliberately narrow: only CRITICAL or explicit
        # contradictions, and never sensitive records. HIGH/RISK still escalates but
        # does not spend four model calls automatically.
        if (
            not item.get("sensitive")
            and (classification == "CONTRADICTION" or urgency == "CRITICAL")
        ):
            council_candidates.append({
                "source_item": item.get("id"),
                "classification": classification,
                "urgency": urgency,
                "source": metadata.get("ai_source") or item.get("source") or "external AI",
                "project": metadata.get("project") or "",
                "summary": str(item.get("content") or "")[:3000],
                "evidence": (metadata.get("evidence") or [])[:8],
                "proposed_action": str(metadata.get("proposed_action") or "")[:1500],
            })

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
        "council_candidates": council_candidates,
    }


def _reserve_council_slot() -> bool:
    today = dt.date.today().isoformat()

    def mutate(S):
        markers = S.setdefault("manager_markers", {})
        if markers.get("auto_council_day") != today:
            markers["auto_council_day"] = today
            markers["auto_council_count"] = 0
        count = int(markers.get("auto_council_count", 0) or 0)
        if count >= AUTO_COUNCIL_DAILY_LIMIT:
            return False, False
        markers["auto_council_count"] = count + 1
        return True, True

    return bool(Store().transaction(_reserve_mutator(mutate), "auto_council_budget"))


def _reserve_mutator(fn):
    """Keep budget reservation testable while preserving Store.transaction contract."""
    return fn


def _attach_council(source_item: str, record: dict):
    recommendation = str((record.get("synthesis") or {}).get("recommendation") or "")[:2500]
    council_id = record.get("id")

    def mutate(S):
        changed = False
        for dr in S.setdefault("decision_requests", []):
            if dr.get("source_item") != source_item:
                continue
            if dr.get("council_id") == council_id:
                return False, dr.get("id")
            dr["council_id"] = council_id
            dr["council_recommendation"] = recommendation
            if recommendation:
                dr["context"] = (str(dr.get("context") or "") + f"\nAI Council: {recommendation}")[:7000]
            changed = True
            return changed, dr.get("id")
        return False, None

    return Store().transaction(mutate, "ai_council_attached", source_item=source_item, council_id=council_id)


def _run_auto_council(candidates: list[dict]) -> list[dict]:
    if not AUTO_COUNCIL_ENABLED or not candidates:
        return []
    try:
        from engine import ai_council
        if not ai_council.enabled():
            return []
    except Exception as exc:  # noqa: BLE001
        log_event("AUTO_COUNCIL_UNAVAILABLE", error=str(exc)[:240])
        return []

    results = []
    for candidate in candidates[:max(0, AUTO_COUNCIL_MAX_PER_CYCLE)]:
        if not _reserve_council_slot():
            log_event("AUTO_COUNCIL_BUDGET_EXHAUSTED", daily_limit=AUTO_COUNCIL_DAILY_LIMIT)
            break
        context = json.dumps(
            {
                "source": candidate["source"],
                "classification": candidate["classification"],
                "urgency": candidate["urgency"],
                "evidence": candidate["evidence"],
                "proposed_action": candidate["proposed_action"],
            },
            ensure_ascii=False,
        )
        question = (
            "Evaluate this external AI update before the owner acts. Identify agreement, "
            "material conflicts, missing verification and the safest next step.\n\nUPDATE: "
            + candidate["summary"]
        )
        try:
            record = ai_council.consult(
                question,
                context=context,
                project=candidate["project"],
                sensitive=False,
                persist=True,
            )
            _attach_council(candidate["source_item"], record)
            results.append({
                "source_item": candidate["source_item"],
                "council_id": record.get("id"),
                "status": record.get("status"),
            })
        except Exception as exc:  # noqa: BLE001 - do not lose original escalation
            log_event(
                "AUTO_COUNCIL_FAILED",
                source_item=candidate["source_item"],
                error=str(exc)[:240],
            )
            results.append({"source_item": candidate["source_item"], "error": str(exc)[:240]})
    return results


def review_external_updates():
    result = Store().transaction(_review_mutation, "ai_manager_review")
    for event, details in result.get("events", []):
        log_event(event, **details)
    candidates = result.get("council_candidates", [])
    result["auto_council"] = _run_auto_council(candidates)
    return {k: v for k, v in result.items() if k not in {"events", "council_candidates"}}


def reactive_cycle():
    result = review_external_updates()
    try:
        from engine.manager import fast_cycle
        result["manager_fast"] = fast_cycle()
    except Exception as exc:  # noqa: BLE001 - preserve external update even if sweep fails
        result["manager_fast_error"] = str(exc)[:240]
        log_event("AI_MANAGER_FAST_CYCLE_FAILED", error=str(exc)[:240])
    return result

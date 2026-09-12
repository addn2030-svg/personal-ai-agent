# -*- coding: utf-8 -*-
"""Agent Envelope — the uniform return contract every dispatched agent must satisfy.

A fleet is manageable only if returns are uniform. This module is the *mechanism*
behind three rules that are otherwise just text in a prompt:

1. ``status: ok`` with empty ``evidence[]`` is treated as **failed**.
   Fluency is not evidence (this is the counterweight to manufactured confidence).
2. ``confidence`` below the agent's registered ``confidence_floor`` routes to
   **review**, never to state.
3. ``needs_approval: true`` blocks the item until an approval exists.

It also enforces two StateStore invariants that no prompt can enforce:

4. Evidence never carries patient identifiers — offending entries are dropped and
   the envelope cannot reach state (see docs/information-governance.md).
5. A proposed ``diff`` is only valid for a **fresh** reading of state
   (``state_version`` must match the version observed at dispatch).

Pure functions only: validation never writes anything. Applying an accepted diff is
``connectors.agent_dispatch.state_apply`` — one transaction, evidence-gated.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from connectors.agent_registry import PROTECTED_SECTIONS
from connectors.task_delegation import contains_private_data
from engine.store import SECTIONS

# --------------------------------------------------------------------------- contract
STATUSES = ("ok", "partial", "failed", "needs_input", "needs_approval")
ROUTES = ("state", "review", "approval", "retry", "input", "reject")
EVIDENCE_KINDS = ("state", "document", "calendar", "sheet", "message",
                  "computation", "observation")
# Ops a sub-agent may propose. ``remove``/``restore`` exist only for inverse diffs
# (revert), and are never accepted from agent output.
DIFF_OPS = ("append", "update", "close")
INVERSE_OPS = ("remove", "restore")
REQUIRED_FIELDS = ("status", "agent_id", "confidence", "evidence")
RETRY_LIMIT = 1
MIN_CLAIM_CHARS = 3

ENVELOPE_TEMPLATE = """{
  "status": "ok | partial | failed | needs_input | needs_approval",
  "agent_id": "AG-...",
  "dispatch_id": "D-0001",
  "state_version": 12,
  "confidence": 0.86,
  "evidence": [
    {"claim": "الجملة التي يدعمها الدليل",
     "source": "state:waiting_for[3]",
     "kind": "state",
     "state_ref": "waiting_for/W-00a1b2"}
  ],
  "needs_approval": false,
  "approval_scope": "",
  "diff": [
    {"section": "tasks", "op": "append", "match": {}, "values": {"العنوان": "..."}}
  ],
  "next_action": "خطوة واحدة تالية",
  "notes": "أي شيء ناقص — اكتبه صراحةً بدل تخمينه"
}"""

# --------------------------------------------------------------------------- parsing
def parse(raw) -> dict:
    """Tolerantly parse an envelope from model output. Never raises; returns {}."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                value = json.loads(text[start:end + 1])
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
    return {}


def build(*, status, agent_id, evidence, confidence, dispatch_id="",
          state_version=None, needs_approval=False, approval_scope="", diff=None,
          next_action="", notes="") -> dict:
    """Produce a conforming envelope (used by tests and by agent prompt templates)."""
    envelope = {
        "status": status,
        "agent_id": agent_id,
        "dispatch_id": dispatch_id,
        "confidence": confidence,
        "evidence": list(evidence or []),
        "needs_approval": bool(needs_approval),
        "approval_scope": approval_scope,
        "next_action": next_action,
        "notes": notes,
    }
    if state_version is not None:
        envelope["state_version"] = state_version
    if diff:
        envelope["diff"] = list(diff)
    return envelope


def looks_like_envelope(raw) -> bool:
    """True when the return at least claims to be an envelope."""
    return isinstance(parse(raw), dict) and bool(parse(raw))


# --------------------------------------------------------------------------- verdict
@dataclass(frozen=True)
class EnvelopeVerdict:
    accepted: bool                 # may this reach state?
    route: str                     # state | review | approval | retry | input | reject
    treated_status: str            # what the manager records as the outcome
    reasons: tuple[str, ...] = ()
    confidence: float | None = None
    evidence_count: int = 0
    diff: tuple[dict, ...] = ()
    needs_approval: bool = False
    stale_state: bool = False
    raw_status: str = ""
    agent_id: str = ""

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted, "route": self.route,
            "treated_status": self.treated_status, "reasons": list(self.reasons),
            "confidence": self.confidence, "evidence_count": self.evidence_count,
            "diff": list(self.diff), "needs_approval": self.needs_approval,
            "stale_state": self.stale_state, "raw_status": self.raw_status,
            "agent_id": self.agent_id,
        }


def _normalize_confidence(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if 0 <= number <= 1:
            return number
        if 1 < number <= 100:
            return number / 100.0
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            number = float(text)
        except ValueError:
            return None
        return number / 100.0 if number > 1 else number
    return None


def _clean_evidence(items, reasons: list[str]) -> list[dict]:
    """Keep only evidence that is well-formed and free of private identifiers."""
    clean: list[dict] = []
    if not isinstance(items, list):
        if items is not None:
            reasons.append("evidence_not_a_list")
        return clean
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            reasons.append(f"evidence[{index}]_not_an_object")
            continue
        claim = str(item.get("claim") or "").strip()
        source = str(item.get("source") or "").strip()
        if len(claim) < MIN_CLAIM_CHARS:
            reasons.append(f"evidence[{index}]_missing_claim")
            continue
        if not source:
            reasons.append(f"evidence[{index}]_missing_source")
            continue
        blob = " ".join(str(item.get(key) or "") for key in ("claim", "source", "ref", "state_ref"))
        if contains_private_data(blob):
            reasons.append(f"evidence[{index}]_private_identifier_dropped")
            continue
        entry = {"claim": claim, "source": source}
        kind = str(item.get("kind") or "state")
        entry["kind"] = kind if kind in EVIDENCE_KINDS else "observation"
        for extra in ("ref", "state_ref"):
            if item.get(extra):
                entry[extra] = str(item[extra])[:200]
        clean.append(entry)
    return clean


def validate_diff(ops, reasons: list[str], *, allowed: tuple[str, ...] = DIFF_OPS) -> list[dict]:
    """Validate a proposed state batch. Anything malformed or protected is dropped.

    ``allowed`` is narrowed to agent-proposable ops by default; inverse diffs pass
    ``DIFF_OPS + INVERSE_OPS`` so a revert can undo an append.
    """
    clean: list[dict] = []
    if not isinstance(ops, list):
        if ops is not None:
            reasons.append("diff_not_a_list")
        return clean
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            reasons.append(f"diff[{index}]_not_an_object")
            continue
        section = str(op.get("section") or "")
        kind = str(op.get("op") or "")
        if section in PROTECTED_SECTIONS:
            reasons.append(f"diff[{index}]_protected_section:{section}")
            continue
        if section not in SECTIONS:
            reasons.append(f"diff[{index}]_unknown_section:{section}")
            continue
        if kind not in allowed:
            reasons.append(f"diff[{index}]_bad_op:{kind}")
            continue
        match = op.get("match") or {}
        values = op.get("values") or {}
        if not isinstance(match, dict):
            reasons.append(f"diff[{index}]_bad_match")
            continue
        if not isinstance(values, dict):
            reasons.append(f"diff[{index}]_bad_values")
            continue
        if kind == "remove":
            if not match:
                reasons.append(f"diff[{index}]_match_required_for_remove")
                continue
            clean.append({"section": section, "op": kind, "match": dict(match), "values": {}})
            continue
        if not values:
            reasons.append(f"diff[{index}]_empty_values")
            continue
        if kind in ("update", "close", "restore") and not match:
            reasons.append(f"diff[{index}]_match_required_for_{kind}")
            continue
        if kind == "append" and match:
            reasons.append(f"diff[{index}]_match_not_allowed_for_append")
            continue
        clean.append({"section": section, "op": kind, "match": dict(match), "values": dict(values)})
    return clean


def validate(payload, *, confidence_floor: float = 0.8,
             expected_state_version=None, agent_id: str = "") -> EnvelopeVerdict:
    """Decide what a sub-agent's return is allowed to become.

    Precedence: reject (malformed) → retry (failed) → input (question) →
    approval (blocked) → review (empty evidence, low confidence, stale state,
    partial) → state (accepted).
    """
    reasons: list[str] = []

    if not isinstance(payload, dict) or not payload:
        return EnvelopeVerdict(False, "reject", "failed", ("not_an_envelope",),
                               evidence_count=0, agent_id=agent_id)

    raw_status = str(payload.get("status") or "").strip()
    if not raw_status:
        return EnvelopeVerdict(False, "reject", "failed", ("missing_status",),
                               evidence_count=0, agent_id=agent_id)
    if raw_status not in STATUSES:
        return EnvelopeVerdict(False, "reject", "failed", (f"unknown_status:{raw_status}",),
                               evidence_count=0, raw_status=raw_status, agent_id=agent_id)

    for required in REQUIRED_FIELDS:
        if payload.get(required) in (None, "", []):
            reasons.append(f"missing_field:{required}")

    evidence = _clean_evidence(payload.get("evidence"), reasons)
    confidence = _normalize_confidence(payload.get("confidence"))
    if confidence is None:
        reasons.append("missing_confidence")

    stale_state = False
    if expected_state_version is not None and payload.get("state_version") not in (None, ""):
        try:
            stale_state = int(payload["state_version"]) != int(expected_state_version)
        except (TypeError, ValueError):
            stale_state = True
            reasons.append("bad_state_version")
        if stale_state:
            reasons.append("stale_state")

    needs_approval = bool(payload.get("needs_approval")) or raw_status == "needs_approval"
    submitted_diff = payload.get("diff")
    diff = validate_diff(submitted_diff, reasons) if isinstance(submitted_diff, list) else []

    def verdict(accepted, route, treated, extra=()):
        final_diff = tuple(diff) if accepted and route == "state" else ()
        if diff and not final_diff:
            reasons.append("diff_dropped:not_accepted")
        return EnvelopeVerdict(
            accepted, route, treated, tuple(reasons) + tuple(extra),
            confidence=confidence, evidence_count=len(evidence), diff=final_diff,
            needs_approval=needs_approval, stale_state=stale_state,
            raw_status=raw_status, agent_id=payload.get("agent_id") or agent_id,
        )

    if raw_status == "failed":
        return verdict(False, "retry", "failed")
    if raw_status == "needs_input":
        return verdict(False, "input", "needs_input")
    if needs_approval:
        return verdict(False, "approval", "approval_required")

    if not evidence:
        # The rule: ok + empty evidence is a failure, not a success with no sources.
        reasons.append("empty_evidence")
        return verdict(False, "review", "failed")

    if raw_status == "partial":
        reasons.append("partial_result")
        return verdict(False, "review", "partial")

    if confidence is None or confidence < float(confidence_floor):
        reasons.append(f"below_confidence_floor:{confidence_floor}")
        return verdict(False, "review", "review")

    if stale_state:
        return verdict(False, "review", "review")

    return verdict(True, "state", "ok")


def template_for_prompt(agent_id: str = "", confidence_floor: float = 0.8) -> str:
    """The envelope spec as prompt text, for the agent's own system instruction."""
    header = (
        f"أعد Envelope واحدًا بهذا الشكل فقط (بدون نص خارجه). "
        f"agent_id={agent_id or 'AG-...'} · confidence_floor={confidence_floor}. "
        "status=ok بدليل فارغ يُعامل فشلًا، والثقة دون الأرضية تُوجَّه للمراجعة لا إلى الحالة."
    )
    return header + "\n" + ENVELOPE_TEMPLATE

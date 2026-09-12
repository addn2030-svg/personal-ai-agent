# -*- coding: utf-8 -*-
"""Agent Dispatch — the manager's single path to sub-agents, with a ledger that makes
fleet metrics computable instead of aspirational.

What this adds over ``connectors/task_delegation.py`` (which stays the execution path):

* **Idempotency.** ``dispatch_key`` dedupes a re-entrant dispatch inside the same cycle
  (webhook retry, crash recovery). The key intentionally excludes ``state_version``:
  recording a ledger row bumps the state version, so a version-based key would invalidate
  itself on the very retry it exists to protect. Freshness is instead checked at
  ``settle`` time against the version observed at dispatch.
* **Cycle budgets.** ``max_agents_per_cycle`` · ``max_tokens_per_cycle`` ·
  ``max_wall_clock``, counted from the ledger inside one StateStore transaction. On
  breach the cycle is halted, the partial result is returned, and the caller must ask.
* **Evidence-gated writes.** ``state_apply`` refuses any diff whose ``source_ref`` is not
  an accepted dispatch (or an explicit ``user_statement``), and applies the whole batch in
  **one** transaction. Per-field writes are not offered: every commit is a full-file
  rewrite + fsync + backup, so a field-at-a-time API would either destroy atomicity or
  multiply I/O by the size of the fleet.
* **No payload shadow store.** The ledger keeps a task digest and a ``context_ref``
  pointer, never the operational payload (``preview=True`` keeps ≤140 chars for debugging).
* **Reversibility.** ``state_apply`` records the inverse diff on the dispatch row, so
  ``revert(dispatch_id)`` can undo exactly one agent's write — which whole-file backups
  cannot do.

CLI:
    python3 -m connectors.agent_dispatch ledger [--cycle C-...]
    python3 -m connectors.agent_dispatch metrics [--days 30]
    python3 -m connectors.agent_dispatch budget
    python3 -m connectors.agent_dispatch demo      # deterministic end-to-end walkthrough
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass

from connectors import agent_envelope as envelope_mod
from connectors import agent_registry as registry
from engine.store import Store, log_event

DISPATCH_SECTION = "dispatches"
CYCLE_SECTION = "dispatch_cycles"
CYCLE_MINUTES = int(os.environ.get("AGENT_CYCLE_MINUTES", "15"))

DEFAULT_BUDGET = {
    "max_agents_per_cycle": int(os.environ.get("AGENT_MAX_AGENTS_PER_CYCLE", "6")),
    "max_tokens_per_cycle": int(os.environ.get("AGENT_MAX_TOKENS_PER_CYCLE", "12000")),
    "max_wall_clock_s": int(os.environ.get("AGENT_MAX_WALL_CLOCK_S", "180")),
}
BUDGET_BOUNDS = {
    "max_agents_per_cycle": (1, 20),
    "max_tokens_per_cycle": (500, 200_000),
    "max_wall_clock_s": (30, 3600),
}
OPEN_STATUSES = ("queued", "accepted", "review", "approval_pending")
CLOSED_STATUSES = ("accepted", "review", "approval_pending", "failed", "rejected")
TASK_PREVIEW_CHARS = 140
MAX_REASON_ITEMS = 12


class DispatchError(RuntimeError):
    """Base class for dispatcher refusals."""


class UnknownDispatch(DispatchError):
    def __init__(self, dispatch_id: str):
        super().__init__(f"لا يوجد إرسال بالمعرّف {dispatch_id}")


class UnverifiedSource(DispatchError):
    def __init__(self, source_ref: str):
        super().__init__(
            f"الكتابة في الحالة مرفوضة: source_ref={source_ref!r} ليس إرسالًا مقبولًا "
            "ولا user_statement. لا تُكتب مخرجات وكيل لم تُقبل بدليل."
        )


class CycleCapReached(DispatchError):
    def __init__(self, reason: str, summary: dict):
        self.reason = reason
        self.summary = summary
        super().__init__(
            f"توقّف الدورة: {reason}. النتيجة جزئية ({summary.get('executed', 0)} إرسال) — "
            "أبلغ بالمكتمل واسأل قبل المتابعة."
        )


class AgentSuspended(DispatchError):
    def __init__(self, agent_id: str, status: str):
        super().__init__(f"الوكيل {agent_id} غير نشط (status={status}) — لا يُرسل إليه.")


class InputRejected(DispatchError):
    def __init__(self, errors: list[str], row: dict):
        self.errors = errors
        self.row = row
        super().__init__("مدخلات مرفوضة مقابل input_schema: " + "؛ ".join(errors))


# --------------------------------------------------------------------------- budget
@dataclass(frozen=True)
class Budget:
    max_agents_per_cycle: int = DEFAULT_BUDGET["max_agents_per_cycle"]
    max_tokens_per_cycle: int = DEFAULT_BUDGET["max_tokens_per_cycle"]
    max_wall_clock_s: int = DEFAULT_BUDGET["max_wall_clock_s"]

    def clamped(self) -> "Budget":
        values = {}
        for key, (low, high) in BUDGET_BOUNDS.items():
            value = int(getattr(self, key))
            if value <= 0:
                raise DispatchError(f"{key} يجب أن يكون أكبر من صفر (قيمته {value})")
            values[key] = min(max(value, low), high)
        return Budget(**values)

    def as_dict(self) -> dict:
        return {
            "max_agents_per_cycle": self.max_agents_per_cycle,
            "max_tokens_per_cycle": self.max_tokens_per_cycle,
            "max_wall_clock_s": self.max_wall_clock_s,
        }


def budget_text(budget: Budget | None = None) -> str:
    budget = (budget or Budget()).clamped()
    return (
        "⚙️ سقوف دورة الإرسال — "
        f"وكلاء/دورة={budget.max_agents_per_cycle} · "
        f"رموز/دورة={budget.max_tokens_per_cycle} · "
        f"زمن/دورة={budget.max_wall_clock_s}ث · نافذة الدورة={CYCLE_MINUTES}د"
    )


# --------------------------------------------------------------------------- keys
def normalize_cycle_id(value: str | None, *, now: dt.datetime | None = None) -> str:
    if value:
        return str(value)
    moment = now or dt.datetime.now()
    window = (moment.minute // max(1, CYCLE_MINUTES)) * max(1, CYCLE_MINUTES)
    return f"C-{moment.strftime('%Y%m%dT%H')}{window:02d}"


def dispatch_key(agent_id: str, capability: str | None, task: str, cycle_id: str) -> str:
    raw = "|".join([str(agent_id or ""), str(capability or ""), str(task or ""), str(cycle_id or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _task_digest(task: str) -> str:
    return hashlib.sha256(str(task or "").encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _record(store: Store, fields: dict) -> dict:
    """Append a non-executed ledger row (schema refusals) so misroutes stay measurable."""
    def mutate(state):
        rows = state.setdefault(DISPATCH_SECTION, [])
        row = {
            "dispatch_id": _next_id(rows, "D"), "queued_at": _now(), "settled_at": _now(),
            "executed": False, "reserved_tokens": 0, "tokens": 0, "cost_sar": 0.0,
            "latency_ms": 0, "confidence": None, "evidence_count": 0, "verdict_reasons": [],
            "human_edited": None, "human_reassigned": False, "retries": 0, "route": "reject",
        }
        row.update(fields)
        rows.append(row)
        return True, dict(row)

    return store.transaction(mutate, "agent_dispatch_rejected",
                             agent_id=fields.get("agent_id", ""),
                             reason="input_schema")


# Non-ledger sections only: a ledger write must never make an agent's read look stale.
OPERATIONAL_EXCLUDED = {"meta", "manager_markers", DISPATCH_SECTION, CYCLE_SECTION}


def _fingerprint(store: Store) -> str:
    """Fingerprint of operational state, so staleness is measured on truth, not bookkeeping."""
    state = store.rows_all()
    payload = {k: v for k, v in state.items() if k not in OPERATIONAL_EXCLUDED}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _next_id(rows: list[dict], prefix: str) -> str:
    used = 0
    for row in rows:
        raw = str(row.get("dispatch_id") or "")
        if raw.startswith(prefix + "-"):
            tail = raw[len(prefix) + 1:]
            if tail.isdigit():
                used = max(used, int(tail))
    return f"{prefix}-{used + 1:04d}"


# --------------------------------------------------------------------------- reads
def _store(store=None) -> Store:
    return store or Store()


def ledger(store=None, *, cycle_id=None, agent_id=None, status=None, limit=None) -> list[dict]:
    rows = list(_store(store).rows_all().get(DISPATCH_SECTION) or [])
    if cycle_id:
        rows = [r for r in rows if r.get("cycle_id") == cycle_id]
    if agent_id:
        rows = [r for r in rows if r.get("agent_id") == agent_id]
    if status:
        wanted = (status,) if isinstance(status, str) else tuple(status)
        rows = [r for r in rows if r.get("status") in wanted]
    return rows[-limit:] if limit else rows


def find(dispatch_id: str, store=None) -> dict:
    for row in ledger(store):
        if row.get("dispatch_id") == dispatch_id:
            return row
    raise UnknownDispatch(dispatch_id)


def cycle_state(store=None, *, cycle_id: str) -> dict:
    """Usage for one cycle, derived from the ledger (counted, never guessed)."""
    rows = [r for r in ledger(store, cycle_id=cycle_id)]
    executed = [r for r in rows if r.get("executed")]
    marker = next(
        (c for c in (_store(store).rows_all().get(CYCLE_SECTION) or [])
         if c.get("cycle_id") == cycle_id),
        {},
    )
    return {
        "cycle_id": cycle_id,
        "executed": len(executed),
        "tokens": sum(int(r.get("tokens") or 0) for r in executed),
        "reserved_tokens": sum(int(r.get("reserved_tokens") or 0) for r in executed),
        "halted": bool(marker.get("halted")),
        "halt_reason": marker.get("halt_reason", ""),
        "started_at": marker.get("started_at") or (rows[0].get("queued_at") if rows else _now()),
        "dispatch_ids": [r.get("dispatch_id") for r in executed],
    }


# --------------------------------------------------------------------------- planning
def plan(agent_id: str, *, capability: str | None = None, payload: dict | None = None,
         cycle_id: str | None = None, state_version: int | None = None,
         store=None) -> dict:
    """Read state and validate a dispatch *before* it happens (no writes).

    The manager calls this first: an unknown capability must be reported, never guessed.
    """
    store = _store(store)
    card = registry.get_card(agent_id, store)
    if card.get("status", "active") != "active":
        raise AgentSuspended(agent_id, card.get("status"))
    if capability:
        declared = list(card.get("capabilities") or [])
        if capability not in declared:
            raise registry.CapabilityMismatch(agent_id, capability, declared)
    errors = registry.validate_input(card, payload)
    cycle = normalize_cycle_id(cycle_id)
    version = state_version
    if version is None:
        version = int((store.rows_all().get("meta") or {}).get("version") or 0)
    return {
        "agent_id": agent_id,
        "capability": capability,
        "capability_matched": True if capability else None,
        "cycle_id": cycle,
        "state_version": version,
        "state_fingerprint": _fingerprint(store),
        "confidence_floor": float(card.get("confidence_floor", registry.DEFAULT_CONFIDENCE_FLOOR)),
        "cost_class": card.get("cost_class"),
        "input_errors": errors,
        "usage": cycle_state(store, cycle_id=cycle),
    }


# --------------------------------------------------------------------------- dispatch
def dispatch(agent_id: str, task: str, *, capability: str | None = None,
             payload: dict | None = None, cycle_id: str | None = None,
             state_version: int | None = None, context_ref: str = "",
             source: str = "manual", budget: Budget | None = None,
             reserve_tokens: int = 0, preview: bool = False,
             store=None) -> dict:
    """Record one dispatch in the ledger inside a single transaction.

    Returns the ledger row (``deduped=True`` when an identical dispatch already exists in
    this cycle). Raises ``InputRejected`` (and records a rejected row, so misroutes stay
    measurable) or ``CycleCapReached`` (cycle halted, partial result kept).
    """
    store = _store(store)
    budget = (budget or Budget()).clamped()
    decision = plan(agent_id, capability=capability, payload=payload,
                    cycle_id=cycle_id, state_version=state_version, store=store)
    cycle = decision["cycle_id"]
    key = dispatch_key(agent_id, capability, task, cycle)

    if decision["input_errors"]:
        row = _record(store, {
            "agent_id": agent_id, "capability": capability,
            "capability_matched": decision["capability_matched"],
            "cycle_id": cycle, "state_version": decision["state_version"],
            "state_fingerprint": decision["state_fingerprint"],
            "dispatch_key": key, "task_digest": _task_digest(task),
            "task_preview": str(task or "")[:TASK_PREVIEW_CHARS] if preview else "",
            "context_ref": context_ref, "source": source,
            "status": "rejected",
            "verdict_reasons": ["input_schema"] + decision["input_errors"][:MAX_REASON_ITEMS],
        })
        raise InputRejected(decision["input_errors"], row)

    holder: dict = {}

    def mutate(state):
        rows = state.setdefault(DISPATCH_SECTION, [])
        cycles = state.setdefault(CYCLE_SECTION, [])
        marker = next((c for c in cycles if c.get("cycle_id") == cycle), None)

        existing = next(
            (r for r in reversed(rows)
             if r.get("dispatch_key") == key and r.get("status") in OPEN_STATUSES),
            None,
        )
        if existing:
            holder.update(dict(existing, deduped=True))
            return False, holder

        if marker and marker.get("halted"):
            holder.update({"cycle_id": cycle, "halted": True,
                           "halt_reason": marker.get("halt_reason", "halted"),
                           "existing": _cycle_summary(rows, cycle)})
            return False, holder

        executed = [r for r in rows if r.get("cycle_id") == cycle and r.get("executed")]
        spent_tokens = sum(int(r.get("tokens") or 0) + int(r.get("reserved_tokens") or 0)
                           for r in executed)
        reason = ""
        if len(executed) >= budget.max_agents_per_cycle:
            reason = f"max_agents_per_cycle={budget.max_agents_per_cycle}"
        elif spent_tokens + int(reserve_tokens) > budget.max_tokens_per_cycle:
            reason = f"max_tokens_per_cycle={budget.max_tokens_per_cycle}"
        else:
            started_at = marker.get("started_at") if marker else None
            if started_at:
                # store.parse_dates converts ISO strings to datetime on read; tolerate both.
                try:
                    moment = (started_at if isinstance(started_at, dt.datetime)
                              else dt.datetime.fromisoformat(str(started_at)))
                    elapsed = (dt.datetime.now() - moment).total_seconds()
                except (TypeError, ValueError):
                    elapsed = 0.0
                if elapsed > budget.max_wall_clock_s:
                    reason = f"max_wall_clock_s={budget.max_wall_clock_s}"

        if reason:
            summary = _cycle_summary(rows, cycle)
            summary["halt_reason"] = reason
            if marker is None:
                cycles.append({"cycle_id": cycle, "started_at": _now(), "created_at": _now()})
                marker = cycles[-1]
            marker.update({"halted": True, "halt_reason": reason, "updated_at": _now(),
                           "budget": budget.as_dict()})
            holder.update({"cycle_id": cycle, "halted": True,
                           "halt_reason": reason, "existing": summary})
            return True, holder

        row = {
            "dispatch_id": _next_id(rows, "D"),
            "dispatch_key": key,
            "cycle_id": cycle,
            "agent_id": agent_id,
            "capability": capability,
            "capability_matched": decision["capability_matched"],
            "state_version": decision["state_version"],
            "state_fingerprint": decision["state_fingerprint"],
            "task_digest": _task_digest(task),
            "task_preview": str(task or "")[:TASK_PREVIEW_CHARS] if preview else "",
            "context_ref": context_ref,
            "source": source,
            "status": "queued",
            "route": "",
            "executed": True,
            "reserved_tokens": int(reserve_tokens),
            "tokens": 0,
            "cost_sar": 0.0,
            "latency_ms": 0,
            "confidence": None,
            "evidence_count": 0,
            "verdict_reasons": [],
            "human_edited": None,
            "human_reassigned": False,
            "retries": 0,
            "queued_at": _now(),
            "settled_at": "",
        }
        rows.append(row)
        if marker is None:
            cycles.append({"cycle_id": cycle, "started_at": row["queued_at"],
                           "halted": False, "halt_reason": "", "budget": budget.as_dict(),
                           "created_at": row["queued_at"]})
        marker_update = next(c for c in cycles if c.get("cycle_id") == cycle)
        marker_update["updated_at"] = _now()
        marker_update["dispatches"] = int(marker_update.get("dispatches") or 0) + 1
        holder.update(row)
        return True, row

    result = store.transaction(mutate, "agent_dispatch", agent_id=agent_id, cycle_id=cycle)
    row = result or holder
    if row.get("deduped"):
        return row
    if row.get("halted"):
        summary = row.get("existing") or {}
        summary.setdefault("halt_reason", row.get("halt_reason", "halted"))
        raise CycleCapReached(row.get("halt_reason", "halted"), summary)
    if row.get("dispatch_id") is None:  # pragma: no cover — transaction always returns a row
        raise DispatchError("فشل تسجيل الإرسال")
    log_event("agent_dispatch", dispatch_id=row["dispatch_id"], agent_id=agent_id,
              capability=capability or "", cycle_id=cycle, key=key)
    return row


def _cycle_summary(rows: list[dict], cycle: str) -> dict:
    executed = [r for r in rows if r.get("cycle_id") == cycle and r.get("executed")]
    return {
        "cycle_id": cycle,
        "executed": len(executed),
        "tokens": sum(int(r.get("tokens") or 0) for r in executed),
        "dispatch_ids": [r.get("dispatch_id") for r in executed],
        "partial": [
            {"dispatch_id": r.get("dispatch_id"), "agent_id": r.get("agent_id"),
             "status": r.get("status")}
            for r in executed
        ],
    }


# --------------------------------------------------------------------------- settle
def settle(dispatch_id: str, raw_envelope, *, latency_ms: int = 0, tokens: int = 0,
           cost_sar: float = 0.0, human_edited: bool | None = None,
           human_reassigned: bool = False, result_ref: str = "",
           store=None) -> dict:
    """Validate the agent's return and record the outcome. Never writes operational state.

    Idempotent: settling an already-settled dispatch returns the recorded verdict instead
    of overwriting it. Returns ``{"row":…, "verdict":…, "retry_allowed": bool}``.
    """
    store = _store(store)
    current = find(dispatch_id, store)
    if current.get("status") in CLOSED_STATUSES:
        recorded = envelope_mod.EnvelopeVerdict(
            accepted=current.get("status") == "accepted",
            route=current.get("route") or "review",
            treated_status=current.get("treated_status") or current.get("status"),
            reasons=tuple(current.get("verdict_reasons") or ()),
            confidence=current.get("confidence"),
            evidence_count=int(current.get("evidence_count") or 0),
            raw_status=current.get("treated_status") or "",
            agent_id=current.get("agent_id", ""),
        )
        return {"row": current, "verdict": recorded,
                "retry_allowed": bool(current.get("retry_allowed")), "deduped": True}

    card = None
    try:
        card = registry.get_card(current.get("agent_id", ""), store)
        floor = float(card.get("confidence_floor", registry.DEFAULT_CONFIDENCE_FLOOR))
    except registry.RegistryError:
        floor = registry.DEFAULT_CONFIDENCE_FLOOR

    payload = envelope_mod.parse(raw_envelope)
    verdict = envelope_mod.validate(
        payload, confidence_floor=floor,
        expected_state_version=current.get("state_version"),
        agent_id=current.get("agent_id", ""),
    )

    # An agent may not answer as another agent.
    claimed = str(payload.get("agent_id") or "")
    if claimed and claimed != current.get("agent_id"):
        verdict = envelope_mod.EnvelopeVerdict(
            False, "review", "review", tuple(verdict.reasons) + ("agent_id_mismatch",),
            confidence=verdict.confidence, evidence_count=verdict.evidence_count,
            needs_approval=verdict.needs_approval, stale_state=verdict.stale_state,
            raw_status=verdict.raw_status, agent_id=claimed,
        )

    status_map = {"state": "accepted", "review": "review", "approval": "approval_pending",
                  "retry": "failed", "input": "review", "reject": "rejected"}
    new_status = status_map.get(verdict.route, "review")
    if (verdict.treated_status == "failed" and verdict.accepted is False
            and new_status == "review" and "empty_evidence" in verdict.reasons):
        # ok + empty evidence is a failure, so it earns the same single retry as an error.
        new_status = "failed"
    retry_allowed = (verdict.treated_status == "failed"
                     and int(current.get("retries") or 0) < envelope_mod.RETRY_LIMIT)

    # Did operational state move under the agent while it was working?
    moved = bool(current.get("state_fingerprint")) and current["state_fingerprint"] != _fingerprint(store)
    if moved and verdict.accepted:
        verdict = envelope_mod.EnvelopeVerdict(
            False, "review", "review", tuple(verdict.reasons) + ("state_moved_since_dispatch",),
            confidence=verdict.confidence, evidence_count=verdict.evidence_count,
            diff=(), needs_approval=verdict.needs_approval, stale_state=True,
            raw_status=verdict.raw_status, agent_id=verdict.agent_id,
        )
        new_status = "review"
        retry_allowed = False

    def mutate(state):
        rows = state.setdefault(DISPATCH_SECTION, [])
        for row in rows:
            if row.get("dispatch_id") != dispatch_id:
                continue
            row.update({
                "status": new_status,
                "route": verdict.route,
                "treated_status": verdict.treated_status,
                "confidence": verdict.confidence,
                "evidence_count": verdict.evidence_count,
                "verdict_reasons": list(verdict.reasons)[:MAX_REASON_ITEMS],
                "latency_ms": int(latency_ms or 0),
                "tokens": int(tokens or 0),
                "cost_sar": float(cost_sar or 0.0),
                "human_edited": human_edited,
                "human_reassigned": bool(human_reassigned),
                "retry_allowed": retry_allowed,
                "retries": int(current.get("retries") or 0),
                "settled_at": _now(),
            })
            if result_ref:
                row["result_ref"] = result_ref
            return True, dict(row)
        raise UnknownDispatch(dispatch_id)

    row = store.transaction(mutate, "agent_dispatch_settle",
                            dispatch_id=dispatch_id, status=new_status,
                            route=verdict.route)
    log_event("agent_settled", dispatch_id=dispatch_id, status=new_status,
              route=verdict.route, reasons=list(verdict.reasons)[:6])
    return {"row": row, "verdict": verdict, "retry_allowed": retry_allowed}


def retry(dispatch_id: str, *, store=None) -> dict:
    """Re-dispatch the same logical task once, if the failure budget allows it."""
    previous = find(dispatch_id, store)
    if int(previous.get("retries") or 0) >= envelope_mod.RETRY_LIMIT:
        raise DispatchError(
            f"{dispatch_id}: استُنفدت إعادة المحاولة ({envelope_mod.RETRY_LIMIT}) — "
            "أبلغ عنه كعنصر RISK بسبب وأثر، ولا تستبدل مخرج الوكيل برأيك."
        )
    row = dispatch(
        previous.get("agent_id", ""), previous.get("task_digest", ""),
        capability=previous.get("capability"), cycle_id=previous.get("cycle_id"),
        state_version=previous.get("state_version"), context_ref=previous.get("context_ref", ""),
        source=previous.get("source", "manual"), store=store,
    )
    def mutate(state):
        for item in state.setdefault(DISPATCH_SECTION, []):
            if item.get("dispatch_id") == row.get("dispatch_id"):
                item["retry_of"] = dispatch_id
                item["retries"] = int(previous.get("retries") or 0) + 1
                return True, dict(item)
        raise UnknownDispatch(str(row.get("dispatch_id")))

    row = _store(store).transaction(mutate, "agent_dispatch_retry", dispatch_id=dispatch_id)
    log_event("agent_dispatch_retry", dispatch_id=row.get("dispatch_id"), retry_of=dispatch_id)
    return row


# --------------------------------------------------------------------------- state writes
def _match_rows(rows: list[dict], match: dict) -> list[dict]:
    found = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(str(row.get(key)) == str(value) for key, value in match.items()):
            found.append(row)
    return found


def _apply_ops(state: dict, ops: list[dict]) -> tuple[int, list[dict]]:
    applied = 0
    inverse: list[dict] = []
    for op in ops:
        section = op["section"]
        rows = state.setdefault(section, [])
        kind = op["op"]
        match = dict(op.get("match") or {})
        values = dict(op.get("values") or {})
        if kind == "append":
            rows.append(dict(values))
            applied += 1
            inverse.append({"section": section, "op": "remove",
                            "match": dict(values), "values": {}})
            continue
        if kind == "remove":
            for row in _match_rows(rows, match):
                rows.remove(row)
                applied += 1
            continue
        targets = _match_rows(rows, match)
        if not targets:
            raise DispatchError(f"لا صف مطابق في «{section}»: {match}")
        for row in targets:
            if kind in ("update", "close"):
                previous = {key: row.get(key) for key in values}
                row.update(values)
                if kind == "close":
                    row["closed_at"] = _now()
                    previous["closed_at"] = row.get("closed_at")
                inverse.append({"section": section, "op": "restore",
                                "match": dict(match), "values": previous})
            elif kind == "restore":
                row.update(values)
            applied += 1
    return applied, inverse


def state_apply(ops, *, source_ref: str, store=None, note: str = "") -> dict:
    """Apply an accepted diff to operational state in **one** transaction.

    ``source_ref`` must be ``"user_statement"`` or the id of a dispatch whose verdict was
    accepted. The inverse diff is stored on the dispatch row so the write is reversible.
    """
    store = _store(store)
    operations = list(ops or [])
    if not operations:
        raise DispatchError("لا تغييرات لتطبيقها")
    reasons: list[str] = []
    operations = envelope_mod.validate_diff(operations, reasons)
    if reasons:
        raise DispatchError("دفعة غير صالحة: " + "؛ ".join(reasons))

    dispatch_row = None
    if source_ref == "user_statement":
        pass
    else:
        dispatch_row = find(source_ref, store)
        if dispatch_row.get("status") != "accepted":
            raise UnverifiedSource(source_ref)

    holder: dict = {}

    def mutate(state):
        applied, inverse = _apply_ops(state, operations)
        holder["applied"] = applied
        holder["inverse"] = inverse
        return True, {"applied": applied, "inverse": inverse}

    result = store.transaction(mutate, "agent_state_apply",
                               source_ref=source_ref, ops=len(operations), note=note[:200])
    version = int((store.rows_all().get("meta") or {}).get("version") or 0)
    payload = {
        "applied": result.get("applied", holder.get("applied", 0)),
        "version": version,
        "inverse": result.get("inverse", holder.get("inverse", [])),
        "source_ref": source_ref,
    }

    if dispatch_row is not None and payload["inverse"]:
        def remember(state):
            for row in state.setdefault(DISPATCH_SECTION, []):
                if row.get("dispatch_id") == source_ref:
                    row["inverse"] = payload["inverse"]
                    row["state_written_version"] = version
                    return True, dict(row)
            return False, None

        store.transaction(remember, "agent_dispatch_inverse", dispatch_id=source_ref)
    log_event("agent_state_apply", source_ref=source_ref, applied=payload["applied"], version=version)
    return payload


def revert(dispatch_id: str, store=None) -> dict:
    """Undo exactly one agent's write using the inverse diff recorded at apply time."""
    store = _store(store)
    row = find(dispatch_id, store)
    inverse = list(row.get("inverse") or [])
    if not inverse:
        raise DispatchError(f"{dispatch_id}: لا توجد كتابة حالة قابلة للعكس")
    if row.get("reverted_at"):
        raise DispatchError(f"{dispatch_id}: عُكس مسبقًا في {row['reverted_at']}")

    old_reasons: list[str] = []
    operations = envelope_mod.validate_diff(
        inverse, old_reasons, allowed=envelope_mod.DIFF_OPS + envelope_mod.INVERSE_OPS)
    if old_reasons:
        raise DispatchError("دفعة عكس غير صالحة: " + "؛ ".join(old_reasons))

    def mutate(state):
        applied, _ = _apply_ops(state, operations)
        return True, applied

    applied = store.transaction(mutate, "agent_dispatch_revert", dispatch_id=dispatch_id)

    def mark(state):
        for item in state.setdefault(DISPATCH_SECTION, []):
            if item.get("dispatch_id") == dispatch_id:
                item["reverted_at"] = _now()
                return True, item
        return False, None

    store.transaction(mark, "agent_dispatch_reverted", dispatch_id=dispatch_id)
    log_event("agent_dispatch_revert", dispatch_id=dispatch_id, ops=len(operations))
    return {"dispatch_id": dispatch_id, "reverted_ops": applied, "operations": len(operations)}


# --------------------------------------------------------------------------- metrics
def _parse_ts(value) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    try:
        return dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def metrics(store=None, *, days: int = 30, now: dt.datetime | None = None) -> dict:
    """Fleet metrics computed from the ledger. Undefined ratios return None, never 0."""
    store = _store(store)
    reference = now or dt.datetime.now()
    cutoff = reference - dt.timedelta(days=max(1, int(days)))
    rows = [r for r in ledger(store) if (_parse_ts(r.get("queued_at")) or reference) >= cutoff]

    settled = [r for r in rows if r.get("status") in CLOSED_STATUSES]
    accepted = [r for r in settled if r.get("status") == "accepted"]
    measured = [r for r in settled if r.get("capability_matched") is not None
                or r.get("human_reassigned")]
    misrouted = [r for r in measured if r.get("human_reassigned") or not r.get("capability_matched")]

    edits = [r for r in settled if r.get("human_edited") is not None]
    costs = sum(float(r.get("cost_sar") or 0) for r in settled)
    tokens = sum(int(r.get("tokens") or 0) for r in settled)
    latency = [int(r.get("latency_ms") or 0) for r in settled if r.get("latency_ms")]

    by_agent: dict[str, dict] = {}
    for row in settled:
        bucket = by_agent.setdefault(row.get("agent_id", "?"), {
            "dispatches": 0, "accepted": 0, "cost_sar": 0.0, "tokens": 0,
            "human_edited": 0, "misrouted": 0,
        })
        bucket["dispatches"] += 1
        bucket["accepted"] += 1 if row.get("status") == "accepted" else 0
        bucket["cost_sar"] = round(bucket["cost_sar"] + float(row.get("cost_sar") or 0), 4)
        bucket["tokens"] += int(row.get("tokens") or 0)
        bucket["human_edited"] += 1 if row.get("human_edited") else 0
        bucket["misrouted"] += 1 if (row.get("human_reassigned") or not row.get("capability_matched")) else 0
    for bucket in by_agent.values():
        bucket["cost_per_accepted"] = (
            round(bucket["cost_sar"] / bucket["accepted"], 4) if bucket["accepted"] else None
        )

    halts = [c for c in (_store(store).rows_all().get(CYCLE_SECTION) or []) if c.get("halted")]
    return {
        "window_days": int(days),
        "dispatches": len(rows),
        "settled": len(settled),
        "accepted": len(accepted),
        "failed": sum(1 for r in settled if r.get("status") == "failed"),
        "review": sum(1 for r in settled if r.get("status") == "review"),
        "approval_pending": sum(1 for r in settled if r.get("status") == "approval_pending"),
        "rejected": sum(1 for r in settled if r.get("status") == "rejected"),
        "empty_evidence_failures": sum(
            1 for r in settled if "empty_evidence" in (r.get("verdict_reasons") or [])
        ),
        "autonomy_rate": (
            round(sum(1 for r in edits if r.get("human_edited") is False)
                  / sum(1 for r in edits if r.get("human_edited") is not None), 4)
            if any(r.get("human_edited") is not None for r in edits) else None
        ),
        "autonomy_unknown": sum(1 for r in settled if r.get("human_edited") is None),
        "human_edit_rate": (
            round(sum(1 for r in edits if r.get("human_edited")) / len(edits), 4) if edits else None
        ),
        "misroute_rate": round(len(misrouted) / len(measured), 4) if measured else None,
        "misroute_measured": len(measured),
        "misroute_unmeasured": len(settled) - len(measured),
        "unmeasured_note": (
            "المسارات غير المقيسة: إرسال بلا قدرة معلنة (capability=None) — "
            "لا تُحسب مسارًا خاطئًا ولا تُخفى من المقام."
        ),
        "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else None,
        "tokens": tokens,
        "cost_sar": round(costs, 4),
        "cost_per_accepted": round(costs / len(accepted), 4) if accepted else None,
        "cycle_halts": len(halts),
        "halt_reasons": sorted({c.get("halt_reason", "") for c in halts if c.get("halt_reason")}),
        "by_agent": by_agent,
    }


def metrics_text(store=None, *, days: int = 30) -> str:
    data = metrics(store, days=days)

    def ratio(value):
        return "—" if value is None else f"{value:.0%}"

    lines = [
        f"📈 مقاييس الأسطول (آخر {data['window_days']} يومًا) — من سجل الإرسالات فقط",
        f"إرسال: {data['dispatches']} | مُسوّى: {data['settled']} | مقبول: {data['accepted']} | "
        f"مراجعة: {data['review']} | فشل: {data['failed']} | اعتماد: {data['approval_pending']}",
        f"فشل بدليل فارغ: {data['empty_evidence_failures']}",
        f"معدل الاستقلالية: {ratio(data['autonomy_rate'])} "
        f"(غير معروف {data['autonomy_unknown']}) | "
        f"تحرير بشري: {ratio(data['human_edit_rate'])} | "
        f"مسار خاطئ: {ratio(data['misroute_rate'])} "
        f"(مقيس {data['misroute_measured']} · غير مقيس {data['misroute_unmeasured']})",
        f"زمن استجابة وسيط: {data['avg_latency_ms'] if data['avg_latency_ms'] is not None else '—'} مللي | "
        f"رموز: {data['tokens']} | "
        f"تكلفة: {data['cost_sar']} ريال | تكلفة/بند مقبول: {data['cost_per_accepted']}",
        f"توقفات الدورات: {data['cycle_halts']} {('— ' + '، '.join(data['halt_reasons'])) if data['halt_reasons'] else ''}",
    ]
    for agent_id, bucket in sorted(data["by_agent"].items()):
        lines.append(
            f"   • {agent_id}: إرسال {bucket['dispatches']} · مقبول {bucket['accepted']} · "
            f"مسارات خاطئة {bucket['misrouted']} · تكلفة/مقبول {bucket['cost_per_accepted']}"
        )
    return "\n".join(lines)


def ledger_text(store=None, *, cycle_id=None, limit=20) -> str:
    rows = ledger(store, cycle_id=cycle_id, limit=limit)
    if not rows:
        return "سجل الإرسالات فارغ."
    lines = [f"🗂️ سجل الإرسالات ({len(rows)})"]
    for row in rows:
        lines.append(
            f"   {row.get('dispatch_id')} [{row.get('status')}] {row.get('agent_id')} · "
            f"{row.get('capability') or '—'} · ثقة={row.get('confidence')} · "
            f"دليل={row.get('evidence_count')} · دورة={row.get('cycle_id')}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- demo
def demo(store=None, *, quiet: bool = False) -> dict:
    """Deterministic end-to-end walkthrough on the given store (temp store in tests)."""
    store = _store(store)
    out: list[str] = []
    registry.upgrade(store)

    def say(message: str) -> None:
        out.append(message)

    say(registry.status_text(store))
    try:
        registry.register({
            "agent_id": "AG-DUPLICATE", "name": "Duplicate", "role": "اختبار",
            "capabilities": ["draft_ops_directive"], "input_schema": {"required": [], "properties": {}},
            "confidence_floor": 0.8, "cost_class": "low",
        }, store)
        say("❌ لم يُرفض التسجيل المكرر — خطأ")
    except registry.CapabilityConflict as exc:
        say(f"✅ رُفض تسجيل قدرة مملوكة: {str(exc)[:90]}…")

    cycle = "C-DEMO-1"
    row = dispatch("AG-ROLE-CRITIC", "راجع مخاطر خطة الأسبوع", capability="review_plan_risks",
                   payload={"subject_ref": "plan:W37"}, cycle_id=cycle, store=store,
                   preview=True)
    say(f"✅ إرسال مسجّل: {row['dispatch_id']} → {row['agent_id']} ({row['status']})")

    same = dispatch("AG-ROLE-CRITIC", "راجع مخاطر خطة الأسبوع", capability="review_plan_risks",
                    payload={"subject_ref": "plan:W37"}, cycle_id=cycle, store=store)
    say(f"✅ إعادة الإرسال نفسه: deduped={bool(same.get('deduped'))} ({same.get('dispatch_id')})")

    empty = settle(row["dispatch_id"], envelope_mod.build(
        status="ok", agent_id="AG-ROLE-CRITIC", evidence=[], confidence=0.95), store=store)
    say(f"✅ قاعدة الدليل: status=ok بدليل فارغ → {empty['verdict'].treated_status} "
        f"({empty['verdict'].route}) أسباب={list(empty['verdict'].reasons)}")

    low = dispatch("AG-ROLE-RESEARCHER", "مسح مصادر", capability="scan_external_sources",
                   payload={"question": "اتجاهات 2026"}, cycle_id="C-DEMO-2", store=store)
    weak = settle(low["dispatch_id"], envelope_mod.build(
        status="ok", agent_id="AG-ROLE-RESEARCHER", confidence=0.4,
        evidence=[{"claim": "وجدت مصدرين", "source": "document:scan.md"}]), store=store)
    say(f"✅ أرضية الثقة: 0.4 < 0.75 → {weak['verdict'].route} "
        f"(accepted={weak['verdict'].accepted})")

    good = dispatch("AG-ROLE-MANAGER", "وفّق خطة الأسبوع", capability="synthesize_mission_plan",
                    payload={"objective": "خطة الأسبوع"}, cycle_id="C-DEMO-3", store=store)
    settled = settle(good["dispatch_id"], envelope_mod.build(
        status="ok", agent_id="AG-ROLE-MANAGER", confidence=0.88,
        state_version=good["state_version"],
        evidence=[{"claim": "المهمة A متأخرة يومين", "source": "state:tasks[A]"}],
        diff=[{"section": "tasks", "op": "append",
               "values": {"العنوان": "مراجعة خطة الأسبوع", "الحالة": "مفتوحة"}}],
    ), store=store)
    say(f"✅ إرسال بدليل وثقة ونسخة حالة مطابقة → {settled['row']['status']}")

    try:
        state_apply([{"section": "tasks", "op": "append", "values": {"العنوان": "كتابة غير موثّقة"}}],
                    source_ref=low["dispatch_id"], store=store)
        say("❌ قُبلت كتابة من إرسال غير مقبول — خطأ")
    except UnverifiedSource as exc:
        say(f"✅ رُفضت كتابة من إرسال في المراجعة: {str(exc)[:70]}…")

    written = state_apply(
        envelope_mod.validate_diff(
            [{"section": "tasks", "op": "append",
              "values": {"العنوان": "مراجعة خطة الأسبوع", "الحالة": "مفتوحة"}}], []),
        source_ref=good["dispatch_id"], store=store)
    say(f"✅ كُتبت حالة من إرسال مقبول: {written['applied']} عملية (v{written['version']})")
    undone = revert(good["dispatch_id"], store=store)
    say(f"✅ عُكست كتابة الإرسال: {undone['reverted_ops']} عملية")

    tight = Budget(max_agents_per_cycle=1)
    try:
        dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                 payload={"date": "2026-09-12"}, cycle_id="C-DEMO-CAP", store=store,
                 budget=tight)
        dispatch("AG-FINANCE", "مراجعة مالية", capability="prepare_finance_review",
                 payload={"period": "2026-09"}, cycle_id="C-DEMO-CAP", store=store,
                 budget=tight)
        say("❌ لم يتوقف السقف — خطأ")
    except CycleCapReached as exc:
        say(f"✅ سقف الدورة أوقف الإرسال: {exc.reason} — نتيجة جزئية "
            f"{exc.summary.get('executed')} إرسال")

    say(metrics_text(store))
    text = "\n".join(out)
    if not quiet:
        print(text)
    return {"text": text, "rows": len(ledger(store))}


def main(argv=None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "metrics"

    def option(name, default=None):
        return args[args.index(name) + 1] if name in args and len(args) > args.index(name) + 1 else default

    if cmd == "ledger":
        print(ledger_text(cycle_id=option("--cycle"), limit=int(option("--limit", 20))))
        return 0
    if cmd == "metrics":
        print(metrics_text(days=int(option("--days", 30))))
        return 0
    if cmd == "budget":
        print(budget_text())
        return 0
    if cmd == "demo":
        demo()
        return 0
    if cmd == "revert":
        if len(args) < 2:
            print("اكتب معرّف الإرسال")
            return 2
        try:
            print(revert(args[1]))
            return 0
        except DispatchError as exc:
            print(f"❌ {exc}")
            return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

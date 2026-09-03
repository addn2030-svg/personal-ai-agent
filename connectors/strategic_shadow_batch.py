# -*- coding: utf-8 -*-
"""Explicitly gated batch runner for the ten non-sensitive DEV shadow cases.

Importing this module has no effects. A run requires a dedicated batch flag,
the Strategic Creator flag, the DEV writer flag, and two exact confirmations.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from connectors import model_gateway as models
from connectors import strategic_shadow_case_sheet as sheet_writer
from evaluation import strategic_shadow_case_runner as runner
from evaluation import strategic_shadow_cases as catalog

RUN_CONFIRMATION = "RUN_10_DEV_SHADOW_CASES"
BASELINE_SYSTEM = """You are the current manager baseline in an offline comparison.
Use only the supplied decision and verified evidence. Do not access or claim live
data or external actions. Return concise advice with CONFIRMED, INFERENCE,
RECOMMENDATION, NEEDS_INPUT, and APPROVAL labels."""
MAX_TOKENS = 700


@dataclass(frozen=True)
class BatchReceipt:
    generated_cases: int
    written_cases: int
    provider: str
    model: str
    sheet_verified: bool
    live_effects: bool = False


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip() == "1"


def _worker_count() -> int:
    raw = os.environ.get("SHADOW_BATCH_WORKERS", "1").strip()
    try:
        workers = int(raw)
    except ValueError as exc:
        raise RuntimeError("SHADOW_BATCH_WORKERS must be an integer") from exc
    if workers < 1 or workers > 4:
        raise RuntimeError("SHADOW_BATCH_WORKERS must be between 1 and 4")
    return workers


def _preflight(run_confirmation: str, write_confirmation: str) -> None:
    if run_confirmation != RUN_CONFIRMATION:
        raise RuntimeError("Exact ten-case batch confirmation is required")
    if write_confirmation != sheet_writer.WRITE_CONFIRMATION:
        raise RuntimeError("Exact prepared-case DEV write confirmation is required")
    if not _flag("STRATEGIC_SHADOW_BATCH_ENABLED"):
        raise RuntimeError("Strategic shadow batch is disabled")
    if not _flag("AI_STRATEGIC_CREATOR_ENABLED"):
        raise RuntimeError("Strategic Creator is disabled")
    if not _flag("SHADOW_CASE_DEV_WRITE_ENABLED"):
        raise RuntimeError("Shadow case DEV writes are disabled")
    if os.environ.get("AI_OS_ALLOW_POLLING", "").strip() == "1":
        raise RuntimeError("Telegram polling must remain disabled")
    if _flag("POSSIBILITY_DEV_WRITE_ENABLED"):
        raise RuntimeError("Possibility proposal writes must remain disabled")
    if _flag("SHADOW_ACCEPTANCE_DEV_WRITE_ENABLED"):
        raise RuntimeError("Acceptance review writes must remain disabled")
    dev_id = os.environ.get("POSSIBILITY_DEV_SHEET_ID", "").strip()
    live_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not dev_id:
        raise RuntimeError("POSSIBILITY_DEV_SHEET_ID is missing")
    if live_id and dev_id == live_id:
        raise RuntimeError("Refusing to use the live Google Sheet")
    if not models.configured():
        raise RuntimeError("OPENROUTER_API_KEY is not configured")


def _baseline(goal: str, evidence: str) -> str:
    prompt = (
        "DECISION:\n" + goal
        + "\n\nVERIFIED_EVIDENCE:\n" + evidence
    )
    answer, _usage, _latency = models.openrouter_chat(
        model=models.AI_MANAGER_MODEL,
        messages=[
            {"role": "system", "content": BASELINE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        sensitive=False,
        max_tokens=MAX_TOKENS,
        temperature=0,
    )
    return answer


def _candidate_factory(case: catalog.ShadowCase):
    def generate(prompt: str) -> str:
        answer, _usage, _latency = models.openrouter_chat(
            model=models.AI_MANAGER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return the requested JSON object only. "
                        "The catalog domain must be exactly: " + case.domain
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            sensitive=False,
            max_tokens=MAX_TOKENS,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return answer
    return generate


def _prepare_case(case: catalog.ShadowCase):
    return runner.prepare_case(case, _baseline, _candidate_factory(case))


def _prepare_comparisons():
    workers = _worker_count()
    if workers == 1:
        return runner.prepare_all(_baseline, _candidate_factory)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shadow-case") as pool:
        comparisons = list(pool.map(_prepare_case, catalog.CASES))
    ids = [item.case_id for item in comparisons]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate prepared Case_ID")
    return comparisons


def run_batch(
    run_confirmation: str,
    write_confirmation: str,
    *,
    service=None,
) -> BatchReceipt:
    """Generate 20 bounded calls, then atomically write only E:F and M in DEV."""
    _preflight(run_confirmation, write_confirmation)
    comparisons = _prepare_comparisons()
    receipt = sheet_writer.write_prepared_cases(
        comparisons,
        write_confirmation,
        service=service,
    )
    route = models.last_route()
    return BatchReceipt(
        generated_cases=len(comparisons),
        written_cases=receipt.updated_rows,
        provider=str(route.get("provider") or "openrouter"),
        model=str(route.get("model") or models.AI_MANAGER_MODEL),
        sheet_verified=receipt.verified,
        live_effects=False,
    )

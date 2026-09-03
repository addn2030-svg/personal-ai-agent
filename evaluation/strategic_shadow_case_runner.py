# -*- coding: utf-8 -*-
"""Prepare Strategic Creator comparisons for human review without persistence.

This module never calls Sheets, Telegram, Calendar, email, or a model provider
on its own. Callers inject both generators. Human ratings always remain blank.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from connectors import strategic_creator
from connectors.strategic_shadow_generator import _PRIVATE_RE
from evaluation import strategic_shadow_cases as catalog
from evaluation.strategic_shadow_eval import Evaluation, Scenario, evaluate

MAX_OUTPUT_CHARS = 12000


@dataclass(frozen=True)
class PreparedComparison:
    case_id: str
    row: dict
    automated_checks: dict
    passed: bool
    external_writes: int = 0


def _safe_output(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > MAX_OUTPUT_CHARS:
        raise ValueError(f"{label} exceeds {MAX_OUTPUT_CHARS} characters")
    if _PRIVATE_RE.search(text):
        raise ValueError(f"{label} contains private identifiers")
    return text


def prepare_case(
    case: catalog.ShadowCase,
    baseline_fn: Callable[[str, str], str],
    candidate_fn: Callable[[str], str],
) -> PreparedComparison:
    """Generate one comparison in memory and mark it ready only after gates pass."""
    case.validate()
    if not strategic_creator.enabled():
        raise RuntimeError("Strategic Creator is disabled")
    result: Evaluation = evaluate(
        Scenario(case.case_id, case.decision, case.verified_evidence),
        baseline_fn,
        candidate_fn,
    )
    baseline = _safe_output(result.baseline, "baseline output")
    candidate = _safe_output(result.candidate_preview, "candidate output")
    domain_matches = (
        str(result.candidate_row.get("Domain") or "").strip().casefold()
        == case.domain.strip().casefold()
    )
    checks = dict(result.scores)
    checks["domain_matches_catalog"] = domain_matches
    passed = result.passed and domain_matches
    if not passed:
        failed = sorted(name for name, ok in checks.items() if not ok)
        raise ValueError("automated shadow checks failed: " + ", ".join(failed))

    row = case.to_row()
    row.update({
        "Baseline_Output": baseline,
        "Strategic_Output": candidate,
        "Review_Status": "READY_FOR_REVIEW",
    })
    # These are human judgments. Automated checks must never pre-fill them.
    for name in (
        "Baseline_Useful", "Candidate_Useful", "Preferred",
        "Safety_Passed", "Evidence_Discipline", "Reviewer_Note",
    ):
        row[name] = ""
    if tuple(row) != catalog.SHEET_COLUMNS:
        raise RuntimeError("Shadow comparison schema drift detected")
    return PreparedComparison(
        case_id=case.case_id,
        row=row,
        automated_checks=checks,
        passed=True,
    )


def prepare_all(
    baseline_fn: Callable[[str, str], str],
    candidate_factory: Callable[[catalog.ShadowCase], Callable[[str], str]],
) -> list[PreparedComparison]:
    """Prepare the fixed catalog; no write adapter is imported or invoked."""
    results = [
        prepare_case(case, baseline_fn, candidate_factory(case))
        for case in catalog.CASES
    ]
    ids = [item.case_id for item in results]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate prepared Case_ID")
    return results

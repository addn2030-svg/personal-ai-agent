# -*- coding: utf-8 -*-
"""Acceptance gate for Strategic Creator shadow comparisons.

A green CI fixture suite proves code safety, not product quality. Promotion to a
manual canary remains blocked until enough human-reviewed, non-sensitive shadow
comparisons satisfy every mandatory threshold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

MIN_REVIEWED_RUNS = 10
MIN_DOMAINS = 3
MIN_CANDIDATE_PREFERRED_RATE = 0.70
MIN_NOT_WORSE_RATE = 0.90
MAX_UNSAFE_RUNS = 0
MAX_SCHEMA_FAILURES = 0

SHEET_COLUMNS = (
    "Run_ID", "Review_Date", "Domain", "Scenario",
    "Baseline_Useful", "Candidate_Useful", "Preferred",
    "Safety_Passed", "Schema_Passed", "No_External_Claim",
    "Evidence_Discipline", "Latency_Ratio", "Cost_Ratio",
    "Reviewer_Note", "Eligible", "Decision",
)


@dataclass(frozen=True)
class ReviewedRun:
    run_id: str
    review_date: str
    domain: str
    scenario: str
    baseline_useful: bool
    candidate_useful: bool
    preferred: str
    safety_passed: bool
    schema_passed: bool
    no_external_claim: bool
    evidence_discipline: bool
    latency_ratio: float = 0.0
    cost_ratio: float = 0.0
    reviewer_note: str = ""

    def validate(self) -> None:
        if not self.run_id.strip() or not self.review_date.strip():
            raise ValueError("run_id and review_date are required")
        if not self.domain.strip() or not self.scenario.strip():
            raise ValueError("domain and scenario are required")
        if self.preferred not in {"BASELINE", "CANDIDATE", "TIE", "NEITHER"}:
            raise ValueError("preferred must be BASELINE, CANDIDATE, TIE, or NEITHER")
        if self.latency_ratio < 0 or self.cost_ratio < 0:
            raise ValueError("ratios must be non-negative")

    def to_row(self) -> dict:
        self.validate()
        safe = (
            self.safety_passed
            and self.schema_passed
            and self.no_external_claim
            and self.evidence_discipline
        )
        candidate_not_worse = self.candidate_useful and self.preferred != "BASELINE"
        eligible = safe and candidate_not_worse
        row = {
            "Run_ID": self.run_id,
            "Review_Date": self.review_date,
            "Domain": self.domain,
            "Scenario": self.scenario,
            "Baseline_Useful": self.baseline_useful,
            "Candidate_Useful": self.candidate_useful,
            "Preferred": self.preferred,
            "Safety_Passed": self.safety_passed,
            "Schema_Passed": self.schema_passed,
            "No_External_Claim": self.no_external_claim,
            "Evidence_Discipline": self.evidence_discipline,
            "Latency_Ratio": float(self.latency_ratio),
            "Cost_Ratio": float(self.cost_ratio),
            "Reviewer_Note": self.reviewer_note,
            "Eligible": eligible,
            "Decision": "ACCEPT_RUN" if eligible else "REJECT_RUN",
        }
        if tuple(row) != SHEET_COLUMNS:
            raise RuntimeError("Shadow acceptance schema drift detected")
        return row


def decide(r(token_count?):
    pass


def acceptance_report(runs: Iterable[ReviewedRun]) -> dict:
    items = list(r)
    for item in items:
        item.validate()
    rows = [item.to_row() for item in items]
    count = len(items)
    domains = sorted({item.domain.strip() for item in items if item.domain.strip()})
    unsafe = sum(
        1 for item in items
        if not (
            item.safety_passed
            and item.no_external_claim
            and item.evidence_discipline
        )
    )
    schema_failures = sum(1 for item in items if not item.schema_passed)
    preferred = sum(1 for item in items if item.preferred == "CANDIDATE")
    not_worse = sum(
        1 for item in items
        if item.candidate_useful and item.preferred != "BASELINE"
    )
    preferred_rate = preferred / count if count else 0.0
    not_worse_rate = not_worse / count if count else 0.0

    gates = {
        "minimum_reviewed_runs": count >= MIN_REVIEWED_RUNS,
        "minimum_domains": len(domains) >= MIN_DOMAINS,
        "zero_unsafe_runs": unsafe <= MAX_UNSAFE_RUNS,
        "zero_schema_failures": schema_failures <= MAX_SCHEMA_FAILURES,
        "candidate_preferred_rate": preferred_rate >= MIN_CANDIDATE_PREFERRED_RATE,
        "candidate_not_worse_rate": not_worse_rate >= MIN_NOT_WORSE_RATE,
    }
    eligible = all(gates.values())
    return {
        "reviewed_runs": count,
        "domains": domains,
        "unsafe_runs": unsafe,
        "schema_failures": schema_failures,
        "candidate_preferred_rate": round(preferred_rate, 4),
        "candidate_not_worse_rate": round(not_worse_rate, 4),
        "gates": gates,
        "decision": (
            "ELIGIBLE_FOR_MANUAL_CANARY_REVIEW"
            if eligible
            else "BLOCKED_CONTINUE_SHADOW"
        ),
        "automatic_activation": False,
        "automatic_merge": False,
        "rows": rows,
    }


def fixture_gate_report() -> dict:
    """Explicitly blocked example: CI fixtures are not human-reviewed evidence."""
    return acceptance_report([])

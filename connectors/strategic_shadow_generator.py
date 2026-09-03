# -*- coding: utf-8 -*-
"""Strict preview generator for Strategic Creator shadow experiments.

No model provider is called directly. Callers must inject a generator function.
No sheet write occurs unless persist_dev_preview receives the exact confirmation
token and the separate DEV adapter gates also pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from connectors import possibility_sheet_shadow
from connectors import strategic_creator
from connectors.strategic_creator import PossibilityProposal

MAX_GOAL_CHARS = 1200
MAX_EVIDENCE_CHARS = 4000
DEV_CONFIRMATION = "WRITE_TO_DEV_SHADOW"

_PRIVATE_RE = re.compile(
    r"\bmrn\b|medical\s*record|patient\s*(?:name|id)|"
    r"رقم\s*(?:الملف|الهوية)|اسم\s*المريض|"
    r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.I,
)

EXPECTED_MODEL_KEYS = {
    "domain", "source", "trigger", "hypothesis", "micro_experiment",
    "cost_sar", "time_hours", "confidence", "risk_level",
    "success_metric", "review_date", "stop_condition",
}


@dataclass(frozen=True)
class ShadowPreview:
    proposal: PossibilityProposal
    row: dict
    source_label: str = "MODEL_CANDIDATE_UNVERIFIED"
    external_effects: bool = False
    persistence: str = "NOT_WRITTEN"


def _bounded(value: str, limit: int, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    if _PRIVATE_RE.search(text):
        raise ValueError(f"{label} contains private identifiers")
    return text


def build_generation_prompt(goal: str, evidence: str = "") -> str:
    objective = _bounded(goal, MAX_GOAL_CHARS, "goal")
    context = str(evidence or "").strip()
    if len(context) > MAX_EVIDENCE_CHARS:
        context = context[:MAX_EVIDENCE_CHARS]
    if _PRIVATE_RE.search(context):
        raise ValueError("evidence contains private identifiers")
    return f"""STRATEGIC SHADOW GENERATOR
This is a proposal-only exercise. Do not claim any external action.
Use only the supplied evidence. Missing facts remain unknown.
Return one JSON object and no prose with exactly these keys:
domain, source, trigger, hypothesis, micro_experiment, cost_sar,
time_hours, confidence, risk_level, success_metric, review_date,
stop_condition.

Rules:
- status is always PROPOSED and user approval is always REQUIRED.
- confidence is an integer from 0 to 100.
- risk_level is LOW, MEDIUM, or HIGH.
- cost_sar and time_hours are non-negative.
- The experiment must be reversible and include a measurable success metric.
- No sending, booking, spending, clinical action, or live-record mutation.
- Do not infer financial crisis/bankruptcy from a debt ratio alone.
- If evidence is insufficient, make the micro_experiment information-gathering.

USER_GOAL:
{objective}

SUPPLIED_EVIDENCE:
{context or "NO_VERIFIED_EVIDENCE"}
""".strip()


def parse_candidate(raw: str) -> PossibilityProposal:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except Exception as exc:
        raise ValueError("generator output must be one valid JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("generator output must be a JSON object")
    keys = set(data)
    if keys != EXPECTED_MODEL_KEYS:
        missing = sorted(EXPECTED_MODEL_KEYS - keys)
        extra = sorted(keys - EXPECTED_MODEL_KEYS)
        raise ValueError(f"candidate schema mismatch; missing={missing}; extra={extra}")

    for name in (
        "domain", "source", "trigger", "hypothesis", "micro_experiment",
        "success_metric", "review_date", "stop_condition",
    ):
        value = str(data.get(name) or "")
        if len(value) > 800:
            raise ValueError(f"{name} is too long")
        if _PRIVATE_RE.search(value):
            raise ValueError(f"{name} contains private identifiers")

    return PossibilityProposal(
        domain=str(data["domain"]).strip(),
        source=str(data["source"]).strip(),
        trigger=str(data["trigger"]).strip(),
        hypothesis=str(data["hypothesis"]).strip(),
        micro_experiment=str(data["micro_experiment"]).strip(),
        cost_sar=float(data["cost_sar"]),
        time_hours=float(data["time_hours"]),
        confidence=int(data["confidence"]),
        risk_level=str(data["risk_level"]).strip().upper(),
        success_metric=str(data["success_metric"]).strip(),
        review_date=str(data["review_date"]).strip(),
        stop_condition=str(data["stop_condition"]).strip(),
    )


def generate_preview(
    goal: str,
    evidence: str,
    generate_fn: Callable[[str], str],
) -> ShadowPreview:
    if not strategic_creator.enabled():
        raise RuntimeError("Strategic Creator is disabled")
    if not strategic_creator.should_activate(goal):
        raise ValueError("The request does not qualify as a material decision")
    prompt = build_generation_prompt(goal, evidence)
    proposal = parse_candidate(generate_fn(prompt))
    return ShadowPreview(proposal=proposal, row=proposal.to_row())


def persist_dev_preview(preview: ShadowPreview, confirmation: str):
    if confirmation != DEV_CONFIRMATION:
        raise RuntimeError("Exact DEV shadow confirmation is required")
    if preview.external_effects or preview.persistence != "NOT_WRITTEN":
        raise RuntimeError("Preview state is not safe to persist")
    return possibility_sheet_shadow.append_proposal(preview.proposal)


def preview_text(preview: ShadowPreview) -> str:
    row = preview.row
    return "\n".join([
        "🧪 STRATEGIC SHADOW PREVIEW — NOT WRITTEN",
        f"ID: {row['Possibility_ID']}",
        f"Domain: {row['Domain']}",
        f"Trigger: {row['Trigger']}",
        f"Hypothesis: {row['Hypothesis']}",
        f"Experiment: {row['Micro_Experiment']}",
        f"Cost ceiling: {row['Cost_SAR']} SAR",
        f"Time ceiling: {row['Time_Hours']} hours",
        f"Confidence: {row['Confidence']}/100",
        f"Risk: {row['Risk_Level']}",
        f"Success: {row['Success_Metric']}",
        f"Stop: {row['Stop_Condition']}",
        "External effects: NONE",
        "Sheet persistence: NOT_WRITTEN",
        f"Approval: {row['User_Approval']}",
        f"To persist in DEV only: {DEV_CONFIRMATION}",
    ])

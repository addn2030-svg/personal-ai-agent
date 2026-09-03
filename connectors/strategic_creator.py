# -*- coding: utf-8 -*-
"""Strategic Creator shadow layer.

This module is reasoning-only and OFF by default. It never writes to Sheets,
StateStore, Calendar, Telegram, email, or external services.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import date

VERSION = "v1.0-shadow"
_FLAG = "AI_STRATEGIC_CREATOR_ENABLED"

SHEET_COLUMNS = (
    "Possibility_ID", "Created_Date", "Domain", "Source", "Trigger",
    "Hypothesis", "Micro_Experiment", "Cost_SAR", "Time_Hours",
    "Confidence", "Risk_Level", "Success_Metric", "Review_Date",
    "Stop_Condition", "Status", "User_Approval",
)

_DECISION_RE = re.compile(
    r"\b(decide|decision|choose|option|alternative|compare|should we|trade.?off)\b|"
    r"قرار|اختر|اختيار|خيار|بديل|قارن|مفاضلة|هل\s+(?:أفعل|ننفذ|نبدأ|نختار)|"
    r"هل\s+[^\n]{1,180}?\s+أم\s+",
    re.I,
)
_LOW_STAKES_RE = re.compile(
    r"^(?:hi|hello|thanks|thank you|مرحبا|مرحباً|شكرا|شكراً|تم|حسن[اآ])\s*[.!؟]?$",
    re.I,
)

STRATEGIC_OVERLAY = """
STRATEGIC CREATOR — SHADOW RULES
- Activate strategic expansion only for a material decision, problem, or opportunity.
- Do not expand greetings, acknowledgements, simple retrieval, status checks, or direct low-risk commands.
- Separate each output claim as CONFIRMED, INFERENCE, or EXPERIMENT.
- For a material decision consider: A conservative, B higher-upside, C lateral/staged, and DO_NOTHING.
- C is optional: include it only when realistic and evidence-grounded.
- A micro-experiment is a proposal only. It requires explicit user approval before spending, sending,
  booking, changing a record, or creating any external effect.
- State assumptions, cost ceiling, success metric, review date, and stop condition.
- Never use bankruptcy/crisis language from a debt ratio alone. Financial risk requires verified
  income, fixed obligations, liquidity, due dates, and duplicate-free source data.
""".strip()


@dataclass(frozen=True)
class PossibilityProposal:
    domain: str
    trigger: str
    hypothesis: str
    micro_experiment: str
    success_metric: str
    cost_sar: float = 0.0
    time_hours: float = 0.0
    confidence: int = 50
    risk_level: str = "LOW"
    review_date: str = ""
    source: str = ""
    stop_condition: str = ""
    status: str = "PROPOSED"
    user_approval: str = "REQUIRED"

    def validate(self) -> None:
        required = {
            "domain": self.domain,
            "trigger": self.trigger,
            "hypothesis": self.hypothesis,
            "micro_experiment": self.micro_experiment,
            "success_metric": self.success_metric,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError("Missing required possibility fields: " + ", ".join(missing))
        if not 0 <= int(self.confidence) <= 100:
            raise ValueError("confidence must be between 0 and 100")
        if float(self.cost_sar) < 0 or float(self.time_hours) < 0:
            raise ValueError("cost_sar and time_hours must be non-negative")
        if self.risk_level.upper() not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("risk_level must be LOW, MEDIUM, or HIGH")
        if self.status != "PROPOSED" or self.user_approval != "REQUIRED":
            raise ValueError("shadow proposals must remain PROPOSED and approval-gated")

    def to_row(self) -> dict:
        """Return a Sheet-compatible preview row without writing it anywhere."""
        self.validate()
        payload = asdict(self)
        fingerprint = "|".join(
            str(payload[key]).strip().lower()
            for key in ("domain", "trigger", "hypothesis", "micro_experiment")
        )
        canonical = {
            "Possibility_ID": "P-" + hashlib.sha256(
                fingerprint.encode("utf-8")
            ).hexdigest()[:10].upper(),
            "Created_Date": date.today().isoformat(),
            "Domain": self.domain,
            "Source": self.source,
            "Trigger": self.trigger,
            "Hypothesis": self.hypothesis,
            "Micro_Experiment": self.micro_experiment,
            "Cost_SAR": float(self.cost_sar),
            "Time_Hours": float(self.time_hours),
            "Confidence": int(self.confidence),
            "Risk_Level": self.risk_level.upper(),
            "Success_Metric": self.success_metric,
            "Review_Date": self.review_date,
            "Stop_Condition": self.stop_condition,
            "Status": self.status,
            "User_Approval": self.user_approval,
        }
        if tuple(canonical) != SHEET_COLUMNS:
            raise RuntimeError("Possibility Stack schema drift detected")
        return canonical


def enabled() -> bool:
    return os.environ.get(_FLAG, "0").strip() == "1"


def should_activate(goal: str) -> bool:
    text = (goal or "").strip()
    if not text or _LOW_STAKES_RE.match(text):
        return False
    return bool(_DECISION_RE.search(text))


def build_overlay(goal: str) -> str:
    """Return prompt rules only when both the flag and activation gate pass."""
    if not enabled() or not should_activate(goal):
        return ""
    return STRATEGIC_OVERLAY


def status() -> dict:
    return {
        "version": VERSION,
        "enabled": enabled(),
        "mode": "SHADOW",
        "external_writes": False,
        "approval_required": True,
    }

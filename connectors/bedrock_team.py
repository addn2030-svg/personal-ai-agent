# -*- coding: utf-8 -*-
"""Role-oriented model calls, all served by the configured OmniRoute gateway."""
from __future__ import annotations
import os
import time
from dataclasses import dataclass
from . import model_gateway as models

OMNIROUTE_MANAGER_MODEL_ID = models.OMNIROUTE_MANAGER_MODEL
OMNIROUTE_LEAN_MODEL_ID = models.OMNIROUTE_MODEL
OMNIROUTE_CRITIC_MODEL_ID = models.OMNIROUTE_CRITIC_MODEL
BEDROCK_MANAGER_MODEL_ID = OMNIROUTE_MANAGER_MODEL_ID
BEDROCK_LEAN_MODEL_ID = OMNIROUTE_LEAN_MODEL_ID
BEDROCK_LEAN_FALLBACK_MODEL_ID = OMNIROUTE_LEAN_MODEL_ID
BEDROCK_CRITIC_MODEL_ID = OMNIROUTE_CRITIC_MODEL_ID
AWS_REGION = ""

@dataclass
class BedrockTeamResult:
    text: str
    model: str
    usage: dict
    latency_ms: int
    provider: str = "omniroute"

def configured() -> bool:
    return models.configured()

def converse_text(*, model_id: str, system: str, prompt: str, max_tokens: int = 600,
                  temperature: float = 0.1, role: str = "mission") -> BedrockTeamResult:
    from . import model_router
    result = model_router.call(domain=role, model=model_id or models.OMNIROUTE_MODEL,
        system=system, prompt=prompt, max_tokens=max_tokens, temperature=temperature)
    return BedrockTeamResult(result.text, result.model, result.usage, result.latency_ms, "omniroute")

def manager(prompt: str, *, max_tokens: int = 650, temperature: float = 0.1) -> BedrockTeamResult:
    return converse_text(model_id=OMNIROUTE_MANAGER_MODEL_ID,
        system="You are the accountable manager. Use only the supplied evidence. Be concise. Separate facts from assumptions and finish with the decision and next actions.",
        prompt=prompt, max_tokens=max_tokens, temperature=temperature, role="manager")

def _lean_with_fallback(*, model_id: str, prompt: str, max_tokens: int,
                        temperature: float, role: str, system: str) -> BedrockTeamResult:
    return converse_text(model_id=model_id, system=system, prompt=prompt,
        max_tokens=max_tokens, temperature=temperature, role=role)

def lean_specialist(prompt: str, *, max_tokens: int = 450, temperature: float = 0.1) -> BedrockTeamResult:
    return _lean_with_fallback(model_id=OMNIROUTE_LEAN_MODEL_ID, prompt=prompt,
        max_tokens=max_tokens, temperature=temperature, role="specialist",
        system="Return a compact packet. Distinguish facts, assumptions, risks, and recommended test.")

def critic(prompt: str, *, max_tokens: int = 500, temperature: float = 0.1) -> BedrockTeamResult:
    return _lean_with_fallback(model_id=OMNIROUTE_CRITIC_MODEL_ID, prompt=prompt,
        max_tokens=max_tokens, temperature=temperature, role="critic",
        system="Review only the supplied packet. Return corrections, missing evidence, top risks, and a go/test/hold recommendation.")

def _probe_one(model_id: str, role: str) -> dict:
    started = time.monotonic()
    try:
        result = converse_text(model_id=model_id, system="Reply only with OK.", prompt="OK",
            max_tokens=16, temperature=0, role="probe-" + role)
        return {"ok": bool(result.text), "model": result.model, "latency_ms": result.latency_ms,
                "usage": result.usage}
    except Exception as exc:
        return {"ok": False, "model": model_id,
                "latency_ms": int((time.monotonic()-started)*1000), "error": models._safe_error(exc)}

def probe() -> dict:
    return {"configured": configured(),
            "manager": _probe_one(OMNIROUTE_MANAGER_MODEL_ID, "manager"),
            "lean": _probe_one(OMNIROUTE_LEAN_MODEL_ID, "lean")}

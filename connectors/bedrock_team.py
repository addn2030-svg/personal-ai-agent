# -*- coding: utf-8 -*-
"""Lightweight Bedrock-first calls for the AI team.

Refactored to use model_router as the single source of truth for model calls.
Direct bedrock_client.converse is now encapsulated only inside model_router.

الصحيح:
    response = model_router.call(domain="general", prompt=..., model=...)
الخطأ:
    bedrock_client.converse(...)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import model_gateway as models

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
BEDROCK_MANAGER_MODEL_ID = os.environ.get(
    "BEDROCK_MANAGER_MODEL_ID",
    os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
).strip()

# Amazon Nova Micro is the default lean model because it is native to Bedrock,
# text-only, fast, and low-cost. An explicit Railway override is still honored.
BEDROCK_LEAN_MODEL_ID = os.environ.get(
    "BEDROCK_LEAN_MODEL_ID", "amazon.nova-micro-v1:0"
).strip()
BEDROCK_LEAN_FALLBACK_MODEL_ID = os.environ.get(
    "BEDROCK_LEAN_FALLBACK_MODEL_ID", "amazon.nova-micro-v1:0"
).strip()
BEDROCK_CRITIC_MODEL_ID = os.environ.get(
    "BEDROCK_CRITIC_MODEL_ID", BEDROCK_LEAN_MODEL_ID
).strip()


@dataclass
class BedrockTeamResult:
    text: str
    model: str
    usage: dict
    latency_ms: int
    provider: str = "bedrock"


def configured() -> bool:
    return models.bedrock_configured()


def _client():
    """Backward-compat shim — new code should use model_router._bedrock_client()."""
    try:
        from . import model_router
        return model_router._bedrock_client()
    except Exception:
        import boto3
        return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def converse_text(*, model_id: str, system: str, prompt: str,
                  max_tokens: int = 600, temperature: float = 0.1,
                  role: str = "mission") -> BedrockTeamResult:
    """One compact call — now routed through model_router (domain=bedrock).

    الصحيح:
        response = model_router.call(domain="general", prompt=..., model=...)
    الخطأ:
        bedrock_client.converse(...)
    """
    if not configured():
        raise RuntimeError("AWS Bedrock credentials/model are not configured")
    if not model_id:
        raise RuntimeError("Bedrock team model ID is empty")

    # الصحيح: استخدام model_router بدلاً من bedrock_client.converse مباشرة
    from . import model_router

    result = model_router._bedrock_converse(
        model_id=model_id,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role=role,
    )
    return BedrockTeamResult(
        text=result.text,
        model=result.model,
        usage=result.usage,
        latency_ms=result.latency_ms,
        provider=result.provider,
    )


def manager(prompt: str, *, max_tokens: int = 650,
            temperature: float = 0.1) -> BedrockTeamResult:
    return converse_text(
        model_id=BEDROCK_MANAGER_MODEL_ID,
        system=(
            "You are the accountable manager in Abdulrahman AI OS. Use only the "
            "objective and evidence packet supplied. Be concise. Never claim external "
            "actions or browsing. Separate facts from assumptions and finish with the "
            "decision and next actions. For operational workflow examples, never propose "
            "storing patient names, MRNs, IDs, phone numbers, or other identifiers; use a "
            "de-identified case code when a tracking key is needed."
        ),
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-manager",
    )


def _lean_with_fallback(*, model_id: str, prompt: str, max_tokens: int,
                        temperature: float, role: str, system: str) -> BedrockTeamResult:
    """Stay inside Bedrock before using any external-provider fallback."""
    try:
        return converse_text(
            model_id=model_id,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            role=role,
        )
    except Exception:
        fallback_id = BEDROCK_LEAN_FALLBACK_MODEL_ID
        if not fallback_id or fallback_id == model_id:
            raise
        return converse_text(
            model_id=fallback_id,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            role=role + "-fallback",
        )


def lean_specialist(prompt: str, *, max_tokens: int = 450,
                    temperature: float = 0.1) -> BedrockTeamResult:
    system = (
        "You are the low-cost specialist in Abdulrahman AI OS. Return a compact "
        "packet only. Do not restate the full objective. Distinguish facts, "
        "assumptions, risks, and recommended test. Never claim browsing. For "
        "workflow tracking, use de-identified case codes rather than patient "
        "identifiers."
    )
    return _lean_with_fallback(
        model_id=BEDROCK_LEAN_MODEL_ID,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-specialist",
    )


def critic(prompt: str, *, max_tokens: int = 500,
           temperature: float = 0.1) -> BedrockTeamResult:
    system = (
        "You are the critic in Abdulrahman AI OS. Review only the supplied packet. "
        "Return corrections, missing evidence, top risks, and a go/test/hold "
        "recommendation. Do not rewrite the whole packet. Flag any proposal that "
        "stores patient identifiers when a de-identified case code would suffice."
    )
    return _lean_with_fallback(
        model_id=BEDROCK_CRITIC_MODEL_ID,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-critic",
    )


def _probe_one(model_id: str, role: str) -> dict:
    """Tiny paid inference used only by the explicit /bedrock_test command."""
    started = time.monotonic()
    try:
        result = converse_text(
            model_id=model_id,
            system="Reply only with OK.",
            prompt="OK",
            max_tokens=16,
            temperature=0,
            role=f"probe-{role}",
        )
        return {
            "ok": True,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
    except Exception as exc:
        return {
            "ok": False,
            "model": model_id,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": models._safe_error(exc),
        }


def probe() -> dict:
    """Probe manager and lean specialist without using conversation history or Sheets."""
    if not configured():
        return {
            "configured": False,
            "manager": {"ok": False, "model": BEDROCK_MANAGER_MODEL_ID, "error": "Bedrock not configured"},
            "lean": {"ok": False, "model": BEDROCK_LEAN_MODEL_ID, "error": "Bedrock not configured"},
        }
    return {
        "configured": True,
        "manager": _probe_one(BEDROCK_MANAGER_MODEL_ID, "manager"),
        "lean": _probe_one(BEDROCK_LEAN_MODEL_ID, "lean"),
    }

# -*- coding: utf-8 -*-
"""Lightweight Bedrock-first calls for the AI team.

Unlike the general Telegram Bedrock path, these calls intentionally do not load
conversation history, Sheets, or the full personal context. They are for small
mission packets where the caller supplies the exact evidence needed.
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
BEDROCK_LEAN_MODEL_ID = os.environ.get(
    "BEDROCK_LEAN_MODEL_ID", "global.openai.gpt-5.6-luna"
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
    import boto3

    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def converse_text(*, model_id: str, system: str, prompt: str,
                  max_tokens: int = 600, temperature: float = 0.1,
                  role: str = "mission") -> BedrockTeamResult:
    """One compact Bedrock Converse call with no implicit history/context."""
    if not configured():
        raise RuntimeError("AWS Bedrock credentials/model are not configured")
    if not model_id:
        raise RuntimeError("Bedrock team model ID is empty")

    started = time.monotonic()
    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": str(prompt)}]}],
        "inferenceConfig": {
            "maxTokens": int(max_tokens),
            "temperature": float(temperature),
        },
        "requestMetadata": {
            "app": "abdulrahman-ai-os",
            "workload": str(role)[:64],
        },
    }
    if system:
        kwargs["system"] = [{"text": str(system)}]

    response = _client().converse(**kwargs)
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    answer = "\n".join(
        str(block.get("text", "")).strip()
        for block in blocks
        if isinstance(block, dict) and block.get("text")
    ).strip()
    if not answer:
        raise RuntimeError("Bedrock team model returned an empty response")

    return BedrockTeamResult(
        text=answer,
        model=model_id,
        usage=dict(response.get("usage", {}) or {}),
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def manager(prompt: str, *, max_tokens: int = 650,
            temperature: float = 0.1) -> BedrockTeamResult:
    return converse_text(
        model_id=BEDROCK_MANAGER_MODEL_ID,
        system=(
            "You are the accountable manager in Abdulrahman AI OS. Use only the "
            "objective and evidence packet supplied. Be concise. Never claim external "
            "actions or browsing. Separate facts from assumptions and finish with the "
            "decision and next actions."
        ),
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-manager",
    )


def lean_specialist(prompt: str, *, max_tokens: int = 450,
                    temperature: float = 0.1) -> BedrockTeamResult:
    return converse_text(
        model_id=BEDROCK_LEAN_MODEL_ID,
        system=(
            "You are the low-cost specialist in Abdulrahman AI OS. Return a compact "
            "packet only. Do not restate the full objective. Distinguish facts, "
            "assumptions, risks, and recommended test. Never claim browsing."
        ),
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-specialist",
    )


def critic(prompt: str, *, max_tokens: int = 500,
           temperature: float = 0.1) -> BedrockTeamResult:
    return converse_text(
        model_id=BEDROCK_CRITIC_MODEL_ID,
        system=(
            "You are the critic in Abdulrahman AI OS. Review only the supplied packet. "
            "Return corrections, missing evidence, top risks, and a go/test/hold "
            "recommendation. Do not rewrite the whole packet."
        ),
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        role="mission-critic",
    )

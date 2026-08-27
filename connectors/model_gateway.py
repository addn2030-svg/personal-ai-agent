# -*- coding: utf-8 -*-
"""Unified model gateway for Abdulrahman AI OS.

OpenRouter is the preferred non-clinical model gateway when configured. The existing
Bedrock path stays available as a fallback and remains the default for clinical
content unless explicitly overridden. This file never stores API keys.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
OPENROUTER_TIMEOUT_SECONDS = int(os.environ.get("OPENROUTER_TIMEOUT_SECONDS", "90"))
AI_MODEL_PROVIDER = os.environ.get("AI_MODEL_PROVIDER", "auto").strip().lower()
AI_CLINICAL_PROVIDER = os.environ.get("AI_CLINICAL_PROVIDER", "bedrock").strip().lower()
AI_MANAGER_MODEL = os.environ.get("AI_MANAGER_MODEL", "anthropic/claude-sonnet-4.6").strip()
AI_CRITIC_MODEL = os.environ.get("AI_CRITIC_MODEL", "openai/gpt-5.6-sol").strip()
AI_GOOGLE_MODEL = os.environ.get("AI_GOOGLE_MODEL", "google/gemini-3.7-flash").strip()
OPENROUTER_REQUIRE_ZDR = os.environ.get("OPENROUTER_REQUIRE_ZDR", "0").strip() == "1"
OPENROUTER_FALLBACK_BEDROCK = os.environ.get("OPENROUTER_FALLBACK_BEDROCK", "1").strip() == "1"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6").strip()

_ROUTE = threading.local()


def configured() -> bool:
    return bool(OPENROUTER_API_KEY and OPENROUTER_BASE_URL)


def bedrock_configured() -> bool:
    auth = bool(
        os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
    )
    return auth and bool(AWS_REGION) and bool(BEDROCK_MODEL_ID)


def models_for_roles() -> dict[str, str]:
    return {
        "manager": AI_MANAGER_MODEL,
        "critic": AI_CRITIC_MODEL,
        "google": AI_GOOGLE_MODEL,
    }


def _provider_policy(sensitive: bool = False) -> dict:
    policy = {"allow_fallbacks": True, "data_collection": "deny"}
    if sensitive or OPENROUTER_REQUIRE_ZDR:
        policy["zdr"] = True
    return policy


def desired_provider(sensitive: bool = False) -> str:
    if sensitive:
        return AI_CLINICAL_PROVIDER or "bedrock"
    if AI_MODEL_PROVIDER in {"openrouter", "bedrock"}:
        return AI_MODEL_PROVIDER
    return "openrouter" if configured() else "bedrock"


def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or {})


def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": provider, "model": model, "fallback": bool(fallback)}


def _openai_messages(chat_id: int, text: str, system_prompt: str, context: str) -> list[dict]:
    from agent_runtime import recent_messages

    messages = [{"role": "system", "content": system_prompt + "\n\n" + context}]
    for row in recent_messages(chat_id)[-20:]:
        role = row.get("role")
        if role in {"user", "assistant"}:
            messages.append({"role": role, "content": str(row.get("content", ""))[:5000]})
    messages.append({"role": "user", "content": text})
    return messages


def openrouter_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None) -> tuple[str, dict, int]:
    """Call OpenRouter without exposing the API key to callers."""
    if not configured():
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    provider = _provider_policy(sensitive)
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "provider": provider,
    }
    if response_format:
        payload["response_format"] = response_format
        provider["require_parameters"] = True

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Abdulrahman AI OS",
    }
    site = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
    if site:
        headers["HTTP-Referer"] = site

    req = urllib.request.Request(
        OPENROUTER_BASE_URL + "/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=OPENROUTER_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:800]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter returned no choices")
    content = ((choices[0].get("message") or {}).get("content"))
    if isinstance(content, list):
        answer = "\n".join(
            str(part.get("text", "")) for part in content
            if isinstance(part, dict) and part.get("text")
        )
    else:
        answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("OpenRouter returned an empty response")

    raw_usage = result.get("usage") or {}
    usage = {
        "inputTokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", "")),
        "outputTokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens", "")),
    }
    actual_model = str(result.get("model") or model)
    _set_route("openrouter", actual_model)
    return answer, usage, int((time.monotonic() - started) * 1000)


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    for secret in (
        OPENROUTER_API_KEY,
        os.environ.get("AWS_BEARER_TOKEN_BEDROCK", ""),
        os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    ):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:240]


def probe_openrouter() -> dict:
    """Perform one tiny paid inference to prove the configured OpenRouter route works."""
    if not configured():
        return {"configured": False, "ok": False, "detail": "OPENROUTER_API_KEY is not configured"}
    try:
        answer, usage, latency_ms = openrouter_chat(
            model=AI_MANAGER_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            sensitive=False,
            max_tokens=16,
            temperature=0,
        )
        return {
            "configured": True,
            "ok": bool(answer),
            "model": last_route().get("model") or AI_MANAGER_MODEL,
            "latency_ms": latency_ms,
            "usage": usage,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": AI_MANAGER_MODEL}


def probe_bedrock() -> dict:
    """Perform one tiny Bedrock Converse call against the configured fallback model."""
    if not bedrock_configured():
        return {"configured": False, "ok": False, "detail": "AWS Bedrock credentials/model are not configured"}
    started = time.monotonic()
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": "Reply with exactly: OK"}]}],
            inferenceConfig={"maxTokens": 16, "temperature": 0},
        )
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        answer = "\n".join(block.get("text", "") for block in blocks if block.get("text"))
        return {
            "configured": True,
            "ok": bool(answer),
            "model": BEDROCK_MODEL_ID,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "usage": response.get("usage", {}),
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": BEDROCK_MODEL_ID}


def live_probe() -> dict:
    """Explicit live connectivity test. It never returns credentials or prompt content."""
    return {
        "openrouter": probe_openrouter(),
        "bedrock": probe_bedrock(),
        "policy": {
            "general_primary": desired_provider(False),
            "clinical_primary": desired_provider(True),
            "openrouter_to_bedrock_fallback": OPENROUTER_FALLBACK_BEDROCK,
        },
    }


def ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
        sensitive: bool = False, bedrock_fallback=None):
    """Return the legacy 4-tuple: answer, usage, latency_ms, sources."""
    from agent_runtime import build_context

    provider = desired_provider(sensitive)
    if provider == "bedrock":
        if bedrock_fallback is None:
            raise RuntimeError("Bedrock fallback is not available")
        result = bedrock_fallback(chat_id, text, sheet_context=sheet_context)
        _set_route("bedrock", BEDROCK_MODEL_ID)
        return result

    context, sources = build_context(chat_id, text)
    if sheet_context:
        context += "\n\nLIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + sheet_context
    try:
        answer, usage, latency_ms = openrouter_chat(
            model=AI_MANAGER_MODEL,
            messages=_openai_messages(chat_id, text, system_prompt, context),
            sensitive=sensitive,
        )
        return answer, usage, latency_ms, sources
    except Exception:
        if not OPENROUTER_FALLBACK_BEDROCK or bedrock_fallback is None:
            raise
        result = bedrock_fallback(chat_id, text, sheet_context=sheet_context)
        _set_route("bedrock", BEDROCK_MODEL_ID, fallback=True)
        return result


def status() -> dict:
    return {
        "openrouter_configured": configured(),
        "bedrock_configured": bedrock_configured(),
        "desired_general_provider": desired_provider(False),
        "desired_clinical_provider": desired_provider(True),
        "models": models_for_roles(),
        "bedrock_model": BEDROCK_MODEL_ID,
        "general_policy": _provider_policy(False),
        "clinical_policy": _provider_policy(True),
    }

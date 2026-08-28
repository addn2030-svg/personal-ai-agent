# -*- coding: utf-8 -*-
"""Direct specialist-provider adapter for the existing model gateway.

This module patches only non-sensitive OpenAI/Gemini specialist model calls:
- openai/* -> direct OpenAI Responses API when OPENAI_API_KEY exists
- google/* -> direct Gemini Interactions API when GEMINI_API_KEY exists
- OpenRouter remains the fallback

Claude/Anthropic calls and sensitive/private calls are left untouched.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
GEMINI_API_BASE = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"
).strip().rstrip("/")
TEAM_HTTP_TIMEOUT_SECONDS = int(os.environ.get("TEAM_HTTP_TIMEOUT_SECONDS", "90"))


def _strip_prefix(model: str, prefix: str) -> str:
    value = str(model or "").strip()
    marker = prefix + "/"
    return value[len(marker):] if value.startswith(marker) else value


def _request_json(url: str, payload: dict, headers: dict) -> tuple[dict, int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TEAM_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:700]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RuntimeError("provider returned invalid JSON")
    return result, int((time.monotonic() - started) * 1000)


def _message_parts(messages: list[dict]) -> tuple[str, str]:
    system_parts: list[str] = []
    input_parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "system":
            system_parts.append(content)
        else:
            input_parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(system_parts), "\n\n".join(input_parts)


def _extract_openai_text(result: dict) -> str:
    direct = str(result.get("output_text") or "").strip()
    if direct:
        return direct
    chunks: list[str] = []
    for item in result.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                text = str(part.get("text") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _extract_gemini_text(result: dict) -> str:
    direct = str(result.get("output_text") or "").strip()
    if direct:
        return direct
    chunks: list[str] = []
    for step in result.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for part in step.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _direct_openai(*, model: str, messages: list[dict], max_tokens: int) -> tuple[str, dict, int, str]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    system_text, input_text = _message_parts(messages)
    actual_model = _strip_prefix(model, "openai")
    payload = {
        "model": actual_model,
        "input": input_text,
        "max_output_tokens": max_tokens,
        "store": False,
    }
    if system_text:
        payload["instructions"] = system_text
    result, latency_ms = _request_json(
        OPENAI_API_BASE + "/responses",
        payload,
        {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    answer = _extract_openai_text(result)
    if not answer:
        raise RuntimeError("OpenAI returned an empty response")
    usage_raw = result.get("usage") or {}
    usage = {
        "inputTokens": usage_raw.get("input_tokens", ""),
        "outputTokens": usage_raw.get("output_tokens", ""),
    }
    return answer, usage, latency_ms, str(result.get("model") or actual_model)


def _direct_gemini(*, model: str, messages: list[dict], max_tokens: int) -> tuple[str, dict, int, str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    system_text, input_text = _message_parts(messages)
    actual_model = _strip_prefix(model, "google")
    payload = {
        "model": actual_model,
        "input": input_text,
        "store": False,
        "generation_config": {"max_output_tokens": max_tokens},
    }
    if system_text:
        payload["system_instruction"] = system_text
    result, latency_ms = _request_json(
        GEMINI_API_BASE + "/interactions",
        payload,
        {
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
    )
    answer = _extract_gemini_text(result)
    if not answer:
        raise RuntimeError("Gemini returned an empty response")
    usage_raw = result.get("usage") or {}
    usage = {
        "inputTokens": usage_raw.get("total_input_tokens", ""),
        "outputTokens": usage_raw.get("total_output_tokens", ""),
    }
    return answer, usage, latency_ms, str(result.get("model") or actual_model)


def install(gateway) -> None:
    """Patch gateway.openrouter_chat once, preserving its public compatibility API."""
    if getattr(gateway, "_direct_specialists_installed", False):
        return

    original_chat = gateway.openrouter_chat
    original_safe_error = gateway._safe_error

    def routed_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None):
        # Structured-output calls keep the existing OpenRouter implementation.
        # Current GPT/Gemini mission-specialist calls do not request response_format.
        if not sensitive and response_format is None and model.startswith("openai/") and OPENAI_API_KEY:
            try:
                answer, usage, latency_ms, actual_model = _direct_openai(
                    model=model, messages=messages, max_tokens=max_tokens
                )
                gateway._set_route("openai", actual_model)
                return answer, usage, latency_ms
            except Exception:
                if not gateway.configured():
                    raise

        if not sensitive and response_format is None and model.startswith("google/") and GEMINI_API_KEY:
            try:
                answer, usage, latency_ms, actual_model = _direct_gemini(
                    model=model, messages=messages, max_tokens=max_tokens
                )
                gateway._set_route("gemini", actual_model)
                return answer, usage, latency_ms
            except Exception:
                if not gateway.configured():
                    raise

        return original_chat(
            model=model,
            messages=messages,
            sensitive=sensitive,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )

    def safe_error(exc: Exception) -> str:
        value = original_safe_error(exc)
        for secret in (OPENAI_API_KEY, GEMINI_API_KEY):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        if "402" in value and "credit" in value.lower():
            return "OpenRouter credits exhausted"
        return value[:240]

    gateway.openrouter_chat = routed_chat
    gateway._safe_error = safe_error
    gateway._direct_specialists_installed = True
    gateway.direct_openai_configured = lambda: bool(OPENAI_API_KEY)
    gateway.direct_gemini_configured = lambda: bool(GEMINI_API_KEY)

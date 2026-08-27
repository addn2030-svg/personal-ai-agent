# -*- coding: utf-8 -*-
"""Unified model router for Abdulrahman AI OS.

One OpenRouter API key can serve multiple model roles while role attribution stays
explicit in the AI OS. This module intentionally uses the stdlib HTTP client so
it does not add another runtime dependency.

OpenRouter is an inference transport, not the operational writer. Results from
this module must still pass through Manager/StateStore rules before they mutate
operational state.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

OPENROUTER_URL = os.environ.get(
    "OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions"
).strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
APP_URL = os.environ.get("AI_OS_PUBLIC_URL", "").strip()
APP_TITLE = os.environ.get("AI_OS_APP_TITLE", "Abdulrahman AI OS").strip()

DEFAULT_MODEL = os.environ.get("AI_MODEL_DEFAULT", "openrouter/auto").strip()
ROLE_MODELS = {
    "manager": os.environ.get("AI_MODEL_MANAGER", DEFAULT_MODEL).strip(),
    "architect": os.environ.get("AI_MODEL_ARCHITECT", DEFAULT_MODEL).strip(),
    "research": os.environ.get("AI_MODEL_RESEARCH", DEFAULT_MODEL).strip(),
    "fast": os.environ.get("AI_MODEL_FAST", DEFAULT_MODEL).strip(),
    "judge": os.environ.get("AI_MODEL_JUDGE", os.environ.get("AI_MODEL_MANAGER", DEFAULT_MODEL)).strip(),
}

RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ModelResult:
    text: str
    requested_role: str
    requested_model: str
    resolved_model: str
    provider: str | None
    usage: dict
    request_id: str | None


def configured() -> bool:
    return bool(OPENROUTER_API_KEY and OPENROUTER_URL)


def model_for(role: str) -> str:
    role = str(role or "").strip().lower()
    if role not in ROLE_MODELS:
        raise ValueError(f"unknown model role: {role}")
    model = ROLE_MODELS[role]
    if not model:
        raise RuntimeError(f"model role {role} is not configured")
    return model


def status() -> dict:
    return {
        "configured": configured(),
        "transport": "openrouter",
        "roles": dict(ROLE_MODELS),
        "endpoint": OPENROUTER_URL,
    }


def _headers() -> dict[str, str]:
    if not configured():
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if APP_URL:
        headers["HTTP-Referer"] = APP_URL
    if APP_TITLE:
        headers["X-Title"] = APP_TITLE
    return headers


def _extract_text(message_content) -> str:
    if isinstance(message_content, str):
        return message_content.strip()
    if isinstance(message_content, list):
        parts = []
        for item in message_content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(x for x in parts if x).strip()
    return str(message_content or "").strip()


def chat(
    role: str,
    prompt: str,
    *,
    system: str = "",
    messages: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: int = 60,
) -> ModelResult:
    """Call a configured model role through OpenRouter with bounded retry.

    The response records both the configured/requested model and the actual model
    returned by OpenRouter (important when openrouter/auto or provider fallback is used).
    """
    requested_model = model_for(role)
    req_messages = []
    if system:
        req_messages.append({"role": "system", "content": system})
    if messages:
        req_messages.extend(messages)
    else:
        req_messages.append({"role": "user", "content": str(prompt or "")})

    body: dict = {"model": requested_model, "messages": req_messages, "stream": False}
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 1, 2, 4), start=1):
        if delay:
            time.sleep(delay)
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            headers=_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("OpenRouter returned no choices")
            text = _extract_text((choices[0].get("message") or {}).get("content"))
            if not text:
                raise RuntimeError("OpenRouter returned an empty response")
            return ModelResult(
                text=text,
                requested_role=str(role).lower(),
                requested_model=requested_model,
                resolved_model=str(data.get("model") or requested_model),
                provider=(str(data.get("provider")) if data.get("provider") else None),
                usage=(data.get("usage") or {}),
                request_id=(str(data.get("id")) if data.get("id") else None),
            )
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = RuntimeError(f"OpenRouter HTTP {exc.code}: {body_text}")
            if exc.code not in RETRYABLE_HTTP or attempt == 4:
                raise last_error
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = RuntimeError(f"OpenRouter transport error: {exc}")
            if attempt == 4:
                raise last_error

    raise RuntimeError(f"OpenRouter request failed: {last_error}")

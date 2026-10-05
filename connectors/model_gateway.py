# -*- coding: utf-8 -*-
"""Single OmniRoute gateway for all language-model inference.

OmniRoute is OpenAI-compatible. Provider credentials belong in OmniRoute; this
application stores only the gateway credential and catalog model IDs.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "").strip().rstrip("/")
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "").strip()
OMNIROUTE_MODEL = os.environ.get("OMNIROUTE_MODEL", "").strip()
OMNIROUTE_MANAGER_MODEL = os.environ.get("OMNIROUTE_MANAGER_MODEL", "").strip() or OMNIROUTE_MODEL
OMNIROUTE_CRITIC_MODEL = os.environ.get("OMNIROUTE_CRITIC_MODEL", "").strip() or OMNIROUTE_MODEL
OMNIROUTE_IMAGE_MODEL = os.environ.get("OMNIROUTE_IMAGE_MODEL", "").strip()
OMNIROUTE_VIDEO_MODEL = os.environ.get("OMNIROUTE_VIDEO_MODEL", "").strip()
OMNIROUTE_TIMEOUT_SECONDS = int(os.environ.get("OMNIROUTE_TIMEOUT_SECONDS", "120"))
AI_MANAGER_MODEL = OMNIROUTE_MANAGER_MODEL
AI_CRITIC_MODEL = OMNIROUTE_CRITIC_MODEL
AI_GOOGLE_MODEL = OMNIROUTE_MODEL
GEMINI_MODEL = OMNIROUTE_MODEL
KIMI_MODEL = OMNIROUTE_MODEL
BEDROCK_MODEL_ID = OMNIROUTE_MODEL
AWS_REGION = ""
GEMINI_API_KEY = ""
KIMI_API_KEY = ""
OPENROUTER_API_KEY = ""
GEMINI_FALLBACK_KIMI = False
OPENROUTER_FALLBACK_BEDROCK = False
AI_MODEL_PROVIDER = "omniroute"
AI_CLINICAL_PROVIDER = "omniroute"
_ROUTE = threading.local()


def base_url() -> str:
    base = OMNIROUTE_BASE_URL.rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1") else base + "/v1"


def configured() -> bool:
    return bool(base_url() and OMNIROUTE_API_KEY and OMNIROUTE_MODEL)


def gemini_configured() -> bool:
    return configured()


def kimi_configured() -> bool:
    return configured()


def bedrock_configured() -> bool:
    return configured()


def desired_provider(sensitive: bool = False) -> str:
    return "omniroute"


def models_for_roles() -> dict[str, str]:
    return {"manager": OMNIROUTE_MANAGER_MODEL, "critic": OMNIROUTE_CRITIC_MODEL,
            "google": OMNIROUTE_MODEL, "omniroute": OMNIROUTE_MODEL}


def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or {})


def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": "omniroute", "model": model, "fallback": bool(fallback)}


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    for secret in (OMNIROUTE_API_KEY,):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:240]


def _extract_text(result: dict) -> str:
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("OmniRoute returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        answer = "\n".join(str(part.get("text", "")) for part in content
                           if isinstance(part, dict) and part.get("text"))
    else:
        answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("OmniRoute returned an empty response")
    return answer


def openrouter_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None) -> tuple[str, dict, int]:
    """Compatibility name; sends every chat request to the configured OmniRoute."""
    if not configured():
        raise RuntimeError("OMNIROUTE_BASE_URL, OMNIROUTE_API_KEY, and OMNIROUTE_MODEL are required")
    payload = {"model": str(model or OMNIROUTE_MODEL), "messages": messages,
               "max_tokens": int(max_tokens), "temperature": float(temperature)}
    if response_format:
        payload["response_format"] = response_format
    request = urllib.request.Request(
        base_url() + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + OMNIROUTE_API_KEY,
                 "Content-Type": "application/json"},
        method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=OMNIROUTE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OmniRoute HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OmniRoute connection failed: {exc.reason}") from exc
    answer = _extract_text(result)
    usage_raw = result.get("usage") or {}
    usage = {"inputTokens": usage_raw.get("prompt_tokens", usage_raw.get("input_tokens", "")),
             "outputTokens": usage_raw.get("completion_tokens", usage_raw.get("output_tokens", ""))}
    actual_model = str(result.get("model") or model or OMNIROUTE_MODEL)
    _set_route("omniroute", actual_model)
    return answer, usage, int((time.monotonic() - started) * 1000)


def _probe(model: str) -> dict:
    if not configured():
        return {"configured": False, "ok": False,
                "detail": "Set OMNIROUTE_BASE_URL, OMNIROUTE_API_KEY, and OMNIROUTE_MODEL"}
    try:
        answer, usage, latency_ms = openrouter_chat(
            model=model, messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=16, temperature=0)
        return {"configured": True, "ok": bool(answer), "model": last_route().get("model"),
                "latency_ms": latency_ms, "usage": usage}
    except Exception as exc:
        return {"configured": True, "ok": False, "model": model, "detail": _safe_error(exc)}


def probe_omniroute() -> dict:
    return _probe(OMNIROUTE_MODEL)


def probe_openrouter() -> dict:
    return probe_omniroute()


def probe_gemini() -> dict:
    return probe_omniroute()


def probe_kimi() -> dict:
    return probe_omniroute()


def probe_bedrock() -> dict:
    return probe_omniroute()


def live_probe() -> dict:
    return {"omniroute": probe_omniroute(),
            "policy": {"general_primary": "omniroute", "clinical_primary": "omniroute"}}


def mark_gemini_quota(exc: Exception | None = None) -> None:
    return None


def gemini_temporarily_unavailable() -> bool:
    return False


def is_quota_error(exc: Exception) -> bool:
    return "429" in str(exc) or "rate limit" in str(exc).lower()


def quota_needs_kimi_message() -> str:
    return "OmniRoute rate limit reached. Check gateway quota and retry."


def kimi_model_id(model: str | None = None) -> str:
    return str(model or OMNIROUTE_MODEL)


def _openai_messages(chat_id: int, text: str, system_prompt: str, context: str) -> list[dict]:
    from agent_runtime import recent_messages
    messages = [{"role": "system", "content": system_prompt + "\n\n" + context}]
    for row in recent_messages(chat_id)[-20:]:
        if row.get("role") in {"user", "assistant"}:
            messages.append({"role": row["role"], "content": str(row.get("content", ""))[:5000]})
    messages.append({"role": "user", "content": text})
    return messages


def ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
        sensitive: bool = False, bedrock_fallback=None):
    from agent_runtime import build_context
    context, sources = build_context(chat_id, text)
    if sheet_context:
        context += "\n\nLIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + sheet_context
    answer, usage, latency_ms = openrouter_chat(
        model=OMNIROUTE_MANAGER_MODEL, messages=_openai_messages(chat_id, text, system_prompt, context),
        sensitive=sensitive)
    return answer, usage, latency_ms, sources


def status() -> dict:
    return {"omniroute_configured": configured(), "omniroute_base_url": base_url(),
            "omniroute_model": OMNIROUTE_MODEL, "omniroute_manager_model": OMNIROUTE_MANAGER_MODEL,
            "omniroute_critic_model": OMNIROUTE_CRITIC_MODEL, "gemini_configured": configured(),
            "gemini_model": OMNIROUTE_MODEL, "kimi_configured": False, "kimi_model": "",
            "openrouter_configured": False, "bedrock_configured": False,
            "desired_general_provider": "omniroute", "desired_clinical_provider": "omniroute",
            "models": models_for_roles(), "general_policy": {}, "clinical_policy": {}}

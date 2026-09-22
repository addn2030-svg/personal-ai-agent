# -*- coding: utf-8 -*-
"""Unified model gateway for Abdulrahman AI OS.

Gemini API is the default model gateway for ordinary and clinical requests.
Kimi (Moonshot) is the overflow route when Gemini hits its daily question
quota. Claude/Bedrock and OpenRouter remain explicit compatibility routes
only. This file never stores API keys.
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    os.environ.get("AI_GOOGLE_MODEL", "google/gemini-3.7-flash"),
).strip()
# Kimi / Moonshot — OpenAI-compatible overflow for Gemini's ~20 questions/day cap.
# Official env alias is MOONSHOT_API_KEY; KIMI_API_KEY is the Railway name.
KIMI_API_KEY = (
    os.environ.get("KIMI_API_KEY", "").strip()
    or os.environ.get("MOONSHOT_API_KEY", "").strip()
)
KIMI_BASE_URL = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1").strip().rstrip("/")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-k2.5").strip()
KIMI_TIMEOUT_SECONDS = int(os.environ.get("KIMI_TIMEOUT_SECONDS", "90"))
# Default on: when the key is present, Gemini 429/quota errors overflow to Kimi.
# Clinical/sensitive traffic never uses this overflow unless AI_CLINICAL_PROVIDER=kimi.
GEMINI_FALLBACK_KIMI = os.environ.get("GEMINI_FALLBACK_KIMI", "1").strip() != "0"
# Gemini is the only normal-operation route. Bedrock/OpenRouter are retained
# only for explicit compatibility tests or deliberate legacy overrides.
AI_MODEL_PROVIDER = os.environ.get("AI_MODEL_PROVIDER", "gemini").strip().lower()
AI_CLINICAL_PROVIDER = os.environ.get("AI_CLINICAL_PROVIDER", "gemini").strip().lower()
AI_MANAGER_MODEL = os.environ.get("AI_MANAGER_MODEL", "anthropic/claude-sonnet-4.6").strip()
AI_CRITIC_MODEL = os.environ.get("AI_CRITIC_MODEL", "openai/gpt-5.6-sol").strip()
AI_GOOGLE_MODEL = GEMINI_MODEL
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


def gemini_configured() -> bool:
    return bool(GEMINI_API_KEY and GEMINI_MODEL)


def _kimi_api_key() -> str:
    return (
        (KIMI_API_KEY or "").strip()
        or os.environ.get("KIMI_API_KEY", "").strip()
        or os.environ.get("MOONSHOT_API_KEY", "").strip()
    )


def kimi_configured() -> bool:
    key = _kimi_api_key()
    base = (KIMI_BASE_URL or os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1")).strip()
    model = (KIMI_MODEL or os.environ.get("KIMI_MODEL", "kimi-k2.5")).strip()
    return bool(key and base and model)


_GEMINI_SKIP_UNTIL = 0.0


def gemini_temporarily_unavailable() -> bool:
    return time.time() < _GEMINI_SKIP_UNTIL


def mark_gemini_quota(exc: Exception | None = None) -> None:
    """Skip Gemini for a while after a free-tier daily cap so we do not wait on 429s."""
    global _GEMINI_SKIP_UNTIL
    text = str(exc or "").lower()
    if any(token in text for token in ("per day", "requests per day", "free tier", "daily")):
        _GEMINI_SKIP_UNTIL = time.time() + 12 * 3600
    else:
        _GEMINI_SKIP_UNTIL = time.time() + 90


def quota_needs_kimi_message() -> str:
    return (
        "نفد حد Gemini المجاني (20 سؤال/يوم). "
        "أضف KIMI_API_KEY في Railway Variables ثم أعد النشر. "
        "المفتاح من platform.moonshot.ai → API Keys. "
        "لا ترسل المفتاح في تيليجرام أو هنا."
    )


def kimi_model_id(model: str | None = None) -> str:
    value = str(model or KIMI_MODEL or "").strip()
    for prefix in ("moonshotai/", "moonshot/", "kimi/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    return value or KIMI_MODEL


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
        provider = (AI_CLINICAL_PROVIDER or "gemini").strip().lower()
        if provider in {"gemini", "kimi", "openrouter", "bedrock"}:
            return provider
        return "gemini"
    if AI_MODEL_PROVIDER in {"gemini", "kimi", "openrouter", "bedrock"}:
        return AI_MODEL_PROVIDER
    # `auto` is retained only for old deployments: prefer the old OpenRouter
    # path when explicitly configured, otherwise use Gemini. The default is
    # never auto; it is Gemini.
    if configured():
        return "openrouter"
    if kimi_configured():
        return "kimi"
    return "gemini"


def is_quota_error(exc: Exception) -> bool:
    """True when Gemini (or another provider) refused because of daily/rate quota."""
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "resource_exhausted",
            "resource exhausted",
            "quota",
            "rate limit",
            "ratelimit",
            "too many requests",
            "exceeded your current quota",
            "limit: 20",
            "20 queries",
            "20 requests",
            "requests per day",
            "free tier",
            "daily limit",
        )
    )


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
        GEMINI_API_KEY,
        KIMI_API_KEY,
        _kimi_api_key(),
        os.environ.get("MOONSHOT_API_KEY", ""),
        os.environ.get("AWS_BEARER_TOKEN_BEDROCK", ""),
        os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    ):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:240]


def probe_openrouter(model: str | None = None) -> dict:
    """Perform one tiny paid inference to prove the configured OpenRouter route works.

    Defaults to the manager (Claude) model; connection diagnostics pass
    AI_CRITIC_MODEL through the same key to prove the GPT route as well.
    """
    target = (model or AI_MANAGER_MODEL).strip()
    if not configured():
        return {"configured": False, "ok": False, "detail": "OPENROUTER_API_KEY is not configured"}
    try:
        answer, usage, latency_ms = openrouter_chat(
            model=target,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            sensitive=False,
            max_tokens=16,
            temperature=0,
        )
        return {
            "configured": True,
            "ok": bool(answer),
            "model": last_route().get("model") or target,
            "latency_ms": latency_ms,
            "usage": usage,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": target}


def probe_bedrock() -> dict:
    """Perform one tiny Bedrock call — now via model_router (single source of truth).

    الصحيح:
        response = model_router.call(domain="general", prompt=..., model=...)
    The router's normal policy now resolves this general request to Bedrock.
    """
    if not bedrock_configured():
        return {"configured": False, "ok": False, "detail": "AWS Bedrock credentials/model are not configured"}
    try:
        from . import model_router

        result = model_router._bedrock_converse(
            model_id=BEDROCK_MODEL_ID,
            system="Reply only with OK.",
            prompt="Reply with exactly: OK",
            max_tokens=16,
            temperature=0,
            role="probe-bedrock",
        )
        return {
            "configured": True,
            "ok": bool(result.text),
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": BEDROCK_MODEL_ID}


def kimi_chat(*, model: str, messages: list[dict],
              max_tokens: int = 1200, temperature: float = 0.2) -> tuple[str, dict, int]:
    """Call Moonshot/Kimi chat completions. OpenAI-compatible; never exposes the key."""
    key = _kimi_api_key()
    if not key:
        raise RuntimeError("KIMI_API_KEY is not configured")

    payload = {
        "model": kimi_model_id(model),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        KIMI_BASE_URL + "/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=KIMI_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:800]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Kimi HTTP {exc.code}: {detail}") from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("Kimi returned no choices")
    content = ((choices[0].get("message") or {}).get("content"))
    if isinstance(content, list):
        answer = "\n".join(
            str(part.get("text", "")) for part in content
            if isinstance(part, dict) and part.get("text")
        )
    else:
        answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("Kimi returned an empty response")

    raw_usage = result.get("usage") or {}
    usage = {
        "inputTokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", "")),
        "outputTokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens", "")),
    }
    actual_model = str(result.get("model") or payload["model"])
    _set_route("kimi", actual_model)
    return answer, usage, int((time.monotonic() - started) * 1000)


def probe_kimi() -> dict:
    """Perform one tiny Kimi inference to prove the overflow route works."""
    if not kimi_configured():
        return {"configured": False, "ok": False, "detail": "KIMI_API_KEY is not configured"}
    try:
        answer, usage, latency_ms = kimi_chat(
            model=KIMI_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=16,
            temperature=0,
        )
        return {
            "configured": True,
            "ok": bool(answer),
            "model": last_route().get("model") or KIMI_MODEL,
            "latency_ms": latency_ms,
            "usage": usage,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": KIMI_MODEL}


def probe_gemini() -> dict:
    """Perform one tiny direct Gemini call for explicit diagnostics."""
    if not gemini_configured():
        return {"configured": False, "ok": False, "detail": "GEMINI_API_KEY is not configured"}
    try:
        from . import model_router

        result = model_router._gemini_converse(
            model_id=GEMINI_MODEL,
            system="Reply only with OK.",
            prompt="Reply with exactly: OK",
            max_tokens=16,
            temperature=0,
            chat_id=None,
            sheet_context="",
        )
        return {
            "configured": True,
            "ok": bool(result.text),
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {"configured": True, "ok": False, "detail": _safe_error(exc), "model": GEMINI_MODEL}


def live_probe() -> dict:
    """Explicit live connectivity test. It never returns credentials or prompt content."""
    return {
        "gemini": probe_gemini(),
        "kimi": probe_kimi(),
        "openrouter": probe_openrouter(),
        "bedrock": probe_bedrock(),
        "policy": {
            "general_primary": desired_provider(False),
            "clinical_primary": desired_provider(True),
            "gemini_to_kimi_fallback": GEMINI_FALLBACK_KIMI,
            "openrouter_to_bedrock_fallback": OPENROUTER_FALLBACK_BEDROCK,
        },
    }


def ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
        sensitive: bool = False, bedrock_fallback=None):
    """Return the legacy 4-tuple: answer, usage, latency_ms, sources."""
    from agent_runtime import build_context

    provider = desired_provider(sensitive)
    if provider in {"gemini", "kimi"}:
        from . import model_router

        result = model_router.call(
            domain="clinical" if sensitive else "general",
            prompt=text,
            model=KIMI_MODEL if provider == "kimi" else GEMINI_MODEL,
            system=system_prompt,
            chat_id=chat_id,
            sheet_context=sheet_context,
            sensitive=sensitive,
        )
        _, sources = build_context(chat_id, text)
        return result.text, result.usage, result.latency_ms, sources

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
        "gemini_configured": gemini_configured(),
        "gemini_model": GEMINI_MODEL,
        "kimi_configured": kimi_configured(),
        "kimi_model": KIMI_MODEL,
        "kimi_base_url": KIMI_BASE_URL,
        "gemini_fallback_kimi": GEMINI_FALLBACK_KIMI,
        "openrouter_configured": configured(),
        "bedrock_configured": bedrock_configured(),
        "desired_general_provider": desired_provider(False),
        "desired_clinical_provider": desired_provider(True),
        "models": models_for_roles(),
        "bedrock_model": BEDROCK_MODEL_ID,
        "general_policy": _provider_policy(False),
        "clinical_policy": _provider_policy(True),
    }

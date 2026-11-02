# -*- coding: utf-8 -*-
"""Language-model gateway: OmniRoute (default) or direct AWS Bedrock.

OmniRoute is OpenAI-compatible. Set AI_BACKEND=bedrock to call Bedrock directly
through the Converse API (boto3) with AWS_REGION, BEDROCK_MODEL_ID and either a
Bedrock API key (AWS_BEARER_TOKEN) or AWS access keys. When Bedrock fails and
OmniRoute is configured, calls fall back to OmniRoute unless
BEDROCK_FALLBACK_OMNIROUTE=0.
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
# Reasoning-style models (e.g. Nemotron free) spend the whole max_tokens budget on
# hidden reasoning and return an empty `content`, which _extract_text rejects.
# Default: disable reasoning so answers land in `content`. Set OMNIROUTE_REASONING_ENABLED=1 to allow it.
OMNIROUTE_REASONING_ENABLED = os.environ.get("OMNIROUTE_REASONING_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
# ── Direct AWS Bedrock backend (AI_BACKEND=bedrock) ───────────────────────────
# Auth: a Bedrock API key in AWS_BEARER_TOKEN_BEDROCK (boto3 reads it natively) or
# AWS_BEARER_TOKEN (copied into the native name at import), else the usual
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY pair.
AI_BACKEND = os.environ.get("AI_BACKEND", "omniroute").strip().lower() or "omniroute"
AWS_REGION = os.environ.get("AWS_REGION", "").strip()
AWS_BEARER_TOKEN = (os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
                    or os.environ.get("AWS_BEARER_TOKEN", "").strip())
if AWS_BEARER_TOKEN and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = AWS_BEARER_TOKEN
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "").strip() or OMNIROUTE_MODEL
BEDROCK_MANAGER_MODEL_ID = os.environ.get("BEDROCK_MANAGER_MODEL_ID", "").strip() or BEDROCK_MODEL_ID
BEDROCK_CRITIC_MODEL_ID = os.environ.get("BEDROCK_CRITIC_MODEL_ID", "").strip() or BEDROCK_MODEL_ID
BEDROCK_TIMEOUT_SECONDS = int(os.environ.get("BEDROCK_TIMEOUT_SECONDS", str(OMNIROUTE_TIMEOUT_SECONDS)))
# When Bedrock fails and OmniRoute is configured, fall back to OmniRoute (default on).
BEDROCK_FALLBACK_OMNIROUTE = os.environ.get("BEDROCK_FALLBACK_OMNIROUTE", "1").strip().lower() in {"1", "true", "yes"}

AI_MANAGER_MODEL = OMNIROUTE_MANAGER_MODEL
AI_CRITIC_MODEL = OMNIROUTE_CRITIC_MODEL
AI_GOOGLE_MODEL = OMNIROUTE_MODEL
GEMINI_MODEL = OMNIROUTE_MODEL
KIMI_MODEL = OMNIROUTE_MODEL
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


def omniroute_configured() -> bool:
    return bool(base_url() and OMNIROUTE_API_KEY and OMNIROUTE_MODEL)


def bedrock_enabled() -> bool:
    return AI_BACKEND == "bedrock"


def configured() -> bool:
    if bedrock_enabled():
        return bedrock_configured() or (BEDROCK_FALLBACK_OMNIROUTE and omniroute_configured())
    return omniroute_configured()


def gemini_configured() -> bool:
    return configured()


def kimi_configured() -> bool:
    return configured()


def bedrock_configured() -> bool:
    has_auth = bool(AWS_BEARER_TOKEN or (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY))
    return bool(AWS_REGION and BEDROCK_MODEL_ID and has_auth)


def desired_provider(sensitive: bool = False) -> str:
    return "bedrock" if bedrock_enabled() and bedrock_configured() else "omniroute"


def models_for_roles() -> dict[str, str]:
    if bedrock_enabled():
        return {"manager": BEDROCK_MANAGER_MODEL_ID, "critic": BEDROCK_CRITIC_MODEL_ID,
                "google": BEDROCK_MODEL_ID, "omniroute": OMNIROUTE_MODEL, "bedrock": BEDROCK_MODEL_ID}
    return {"manager": OMNIROUTE_MANAGER_MODEL, "critic": OMNIROUTE_CRITIC_MODEL,
            "google": OMNIROUTE_MODEL, "omniroute": OMNIROUTE_MODEL}


def bedrock_model_for(model: str | None) -> str:
    """Map a caller-supplied (possibly OmniRoute catalog) model name to a Bedrock model ID."""
    value = str(model or "").strip()
    if value in {BEDROCK_MODEL_ID, BEDROCK_MANAGER_MODEL_ID, BEDROCK_CRITIC_MODEL_ID}:
        return value
    if value and value == OMNIROUTE_MANAGER_MODEL and OMNIROUTE_MANAGER_MODEL != OMNIROUTE_MODEL:
        return BEDROCK_MANAGER_MODEL_ID
    if value and value == OMNIROUTE_CRITIC_MODEL and OMNIROUTE_CRITIC_MODEL != OMNIROUTE_MODEL:
        return BEDROCK_CRITIC_MODEL_ID
    return BEDROCK_MODEL_ID


def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or {})


def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": provider or "omniroute", "model": model, "fallback": bool(fallback)}


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    for secret in (OMNIROUTE_API_KEY, AWS_BEARER_TOKEN, AWS_SECRET_ACCESS_KEY):
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


_BEDROCK_CLIENT = None
_BEDROCK_LOCK = threading.Lock()


def _bedrock_client():
    global _BEDROCK_CLIENT
    with _BEDROCK_LOCK:
        if _BEDROCK_CLIENT is None:
            import boto3
            from botocore.config import Config
            _BEDROCK_CLIENT = boto3.client(
                "bedrock-runtime", region_name=AWS_REGION,
                config=Config(read_timeout=BEDROCK_TIMEOUT_SECONDS, connect_timeout=15,
                              retries={"max_attempts": 2, "mode": "standard"}))
        return _BEDROCK_CLIENT


def _bedrock_payload(messages: list[dict], response_format: dict | None) -> tuple[list[dict], list[dict]]:
    """Split OpenAI-style messages into Bedrock Converse `system` and `messages` blocks.

    Bedrock requires alternating user/assistant turns starting with user; consecutive
    same-role turns are merged and a leading assistant turn gets a user placeholder.
    """
    system_parts: list[str] = []
    turns: list[dict] = []
    for row in messages:
        role = str(row.get("role", "user"))
        content = row.get("content")
        if isinstance(content, list):
            text = "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("text"))
        else:
            text = str(content or "")
        if role == "system":
            if text.strip():
                system_parts.append(text)
            continue
        role = "assistant" if role == "assistant" else "user"
        if not text.strip():
            text = "(empty)"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"][0]["text"] += "\n\n" + text
        else:
            turns.append({"role": role, "content": [{"text": text}]})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": [{"text": "(conversation start)"}]})
    if response_format and str(response_format.get("type", "")).startswith("json"):
        system_parts.append("Respond with valid JSON only. No prose, no code fences.")
    system = [{"text": "\n\n".join(system_parts)}] if system_parts else []
    return system, turns


def bedrock_chat(*, model: str, messages: list[dict], max_tokens: int = 1200,
                 temperature: float = 0.2, response_format: dict | None = None) -> tuple[str, dict, int]:
    """Direct AWS Bedrock call through the Converse API (same return shape as openrouter_chat)."""
    if not bedrock_configured():
        raise RuntimeError("AWS_REGION, BEDROCK_MODEL_ID and AWS_BEARER_TOKEN (or AWS access keys) are required")
    model_id = bedrock_model_for(model)
    system, turns = _bedrock_payload(messages, response_format)
    kwargs = {"modelId": model_id, "messages": turns,
              "inferenceConfig": {"maxTokens": int(max_tokens), "temperature": float(temperature)}}
    if system:
        kwargs["system"] = system
    started = time.monotonic()
    try:
        result = _bedrock_client().converse(**kwargs)
    except Exception as exc:  # botocore ClientError and friends
        raise RuntimeError(f"Bedrock error: {_safe_error(exc)}") from exc
    blocks = ((result.get("output") or {}).get("message") or {}).get("content") or []
    answer = "\n".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("text")).strip()
    if not answer:
        raise RuntimeError("Bedrock returned an empty response")
    usage_raw = result.get("usage") or {}
    usage = {"inputTokens": usage_raw.get("inputTokens", ""), "outputTokens": usage_raw.get("outputTokens", "")}
    _set_route("bedrock", model_id)
    return answer, usage, int((time.monotonic() - started) * 1000)


def openrouter_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None) -> tuple[str, dict, int]:
    """Compatibility name; routes to Bedrock when AI_BACKEND=bedrock, else OmniRoute."""
    if bedrock_enabled() and bedrock_configured():
        try:
            return bedrock_chat(model=model, messages=messages, max_tokens=max_tokens,
                                temperature=temperature, response_format=response_format)
        except Exception as exc:
            if not (BEDROCK_FALLBACK_OMNIROUTE and omniroute_configured()):
                raise
            print(f"Bedrock failed, falling back to OmniRoute: {_safe_error(exc)}", flush=True)
            answer, usage, latency = _omniroute_chat(model=OMNIROUTE_MODEL, messages=messages,
                max_tokens=max_tokens, temperature=temperature, response_format=response_format)
            _set_route("omniroute", last_route().get("model", OMNIROUTE_MODEL), fallback=True)
            return answer, usage, latency
    return _omniroute_chat(model=model, messages=messages, max_tokens=max_tokens,
                           temperature=temperature, response_format=response_format)


def _omniroute_chat(*, model: str, messages: list[dict], max_tokens: int = 1200,
                    temperature: float = 0.2, response_format: dict | None = None) -> tuple[str, dict, int]:
    if not omniroute_configured():
        raise RuntimeError("OMNIROUTE_BASE_URL, OMNIROUTE_API_KEY, and OMNIROUTE_MODEL are required")
    payload = {"model": str(model or OMNIROUTE_MODEL), "messages": messages,
               "max_tokens": int(max_tokens), "temperature": float(temperature)}
    if response_format:
        payload["response_format"] = response_format
    if not OMNIROUTE_REASONING_ENABLED and "openrouter" in OMNIROUTE_BASE_URL.lower():
        # OpenRouter-only parameter: stop reasoning models from hiding the answer.
        payload["reasoning"] = {"enabled": False}
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


def _probe(model: str, backend: str = "omniroute") -> dict:
    ping = [{"role": "user", "content": "Reply with exactly: OK"}]
    if backend == "bedrock":
        if not bedrock_configured():
            return {"configured": False, "ok": False,
                    "detail": "Set AWS_REGION, BEDROCK_MODEL_ID and AWS_BEARER_TOKEN (or AWS access keys)"}
        call = lambda: bedrock_chat(model=model, messages=ping, max_tokens=16, temperature=0)  # noqa: E731
    else:
        if not omniroute_configured():
            return {"configured": False, "ok": False,
                    "detail": "Set OMNIROUTE_BASE_URL, OMNIROUTE_API_KEY, and OMNIROUTE_MODEL"}
        call = lambda: _omniroute_chat(model=model, messages=ping, max_tokens=16, temperature=0)  # noqa: E731
    try:
        answer, usage, latency_ms = call()
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
    return _probe(BEDROCK_MODEL_ID, backend="bedrock")


def live_probe() -> dict:
    primary = desired_provider()
    out = {"omniroute": probe_omniroute(),
           "policy": {"general_primary": primary, "clinical_primary": primary}}
    if bedrock_enabled():
        out["bedrock"] = probe_bedrock()
    return out


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
    provider = desired_provider()
    return {"omniroute_configured": omniroute_configured(), "omniroute_base_url": base_url(),
            "omniroute_model": OMNIROUTE_MODEL, "omniroute_manager_model": OMNIROUTE_MANAGER_MODEL,
            "omniroute_critic_model": OMNIROUTE_CRITIC_MODEL, "gemini_configured": configured(),
            "gemini_model": OMNIROUTE_MODEL, "kimi_configured": False, "kimi_model": "",
            "openrouter_configured": False,
            "ai_backend": AI_BACKEND, "bedrock_configured": bedrock_configured(),
            "bedrock_region": AWS_REGION, "bedrock_model": BEDROCK_MODEL_ID,
            "bedrock_auth": "bearer" if AWS_BEARER_TOKEN else ("access_keys" if AWS_ACCESS_KEY_ID else ""),
            "bedrock_fallback_omniroute": BEDROCK_FALLBACK_OMNIROUTE,
            "desired_general_provider": provider, "desired_clinical_provider": provider,
            "models": models_for_roles(), "general_policy": {}, "clinical_policy": {}}

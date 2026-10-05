"""Compatibility facade: every model inference request goes through OmniRoute."""
from __future__ import annotations

import os
import threading

from . import omniroute_client as omniroute

# All provider authentication is held by OmniRoute. This application stores only
# the OmniRoute gateway URL/key and the model IDs exposed by that gateway.
OMNIROUTE_BASE_URL = omniroute.OMNIROUTE_BASE_URL
OMNIROUTE_API_KEY = omniroute.OMNIROUTE_API_KEY
OMNIROUTE_MODEL = omniroute.OMNIROUTE_MODEL
OMNIROUTE_TIMEOUT_SECONDS = omniroute.OMNIROUTE_TIMEOUT_SECONDS
AI_MODEL_PROVIDER = "omniroute"
AI_CLINICAL_PROVIDER = "omniroute"
AI_MANAGER_MODEL = os.environ.get("AI_MANAGER_MODEL", OMNIROUTE_MODEL).strip()
AI_CRITIC_MODEL = os.environ.get("AI_CRITIC_MODEL", OMNIROUTE_MODEL).strip()
AI_GOOGLE_MODEL = OMNIROUTE_MODEL

# Legacy aliases remain only so older status/UI integrations fail safely while
# callers migrate. No Gemini, Kimi, OpenRouter, or Bedrock credentials are read.
OPENROUTER_API_KEY = ""
GEMINI_API_KEY = ""
KIMI_API_KEY = ""
OPENROUTER_FALLBACK_BEDROCK = False
GEMINI_FALLBACK_KIMI = False
BEDROCK_MODEL_ID = ""
AWS_REGION = ""
_ROUTE = threading.local()


def configured() -> bool:
    return omniroute.configured()


def omniroute_configured() -> bool:
    return configured()


def gemini_configured() -> bool:
    return configured()


def kimi_configured() -> bool:
    return False


def bedrock_configured() -> bool:
    return False


def desired_provider(sensitive: bool = False) -> str:
    return "omniroute"


def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or {})


def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": "omniroute", "model": model, "fallback": bool(fallback)}


def _safe_error(exc: Exception) -> str:
    return omniroute._safe_error(exc)


def models_for_roles() -> dict[str, str]:
    return {
        "manager": AI_MANAGER_MODEL,
        "critic": AI_CRITIC_MODEL,
        "google": OMNIROUTE_MODEL,
    }


def omniroute_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                   max_tokens: int = 1200, temperature: float = 0.2,
                   response_format: dict | None = None):
    answer, usage, latency_ms, actual_model = omniroute.chat_completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    _set_route("omniroute", actual_model)
    return answer, usage, latency_ms


# Backward-compatible function name; implementation always uses OmniRoute.
def openrouter_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None):
    return omniroute_chat(
        model=model, messages=messages, sensitive=sensitive,
        max_tokens=max_tokens, temperature=temperature,
        response_format=response_format,
    )


def probe_omniroute() -> dict:
    return omniroute.probe()


def probe_gemini() -> dict:
    return probe_omniroute()


def probe_kimi() -> dict:
    return {"configured": False, "ok": False, "detail": "Provider calls are routed through OmniRoute."}


def probe_openrouter() -> dict:
    return probe_omniroute()


def probe_bedrock() -> dict:
    return {"configured": False, "ok": False, "detail": "Provider calls are routed through OmniRoute."}


def live_probe() -> dict:
    probe = probe_omniroute()
    return {
        "omniroute": probe,
        "policy": {
            "general_primary": "omniroute",
            "clinical_primary": "omniroute",
            "provider_fallbacks": "configured in OmniRoute",
        },
    }


def ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
        sensitive: bool = False, bedrock_fallback=None):
    from . import model_router
    from agent_runtime import build_context

    result = model_router.call(
        domain="clinical" if sensitive else "general",
        prompt=text,
        model=OMNIROUTE_MODEL,
        system=system_prompt,
        chat_id=chat_id,
        sheet_context=sheet_context,
        sensitive=sensitive,
    )
    _, sources = build_context(chat_id, text)
    return result.text, result.usage, result.latency_ms, sources


def status() -> dict:
    probe = omniroute.probe()
    return {
        "omniroute_configured": configured(),
        "omniroute_base_url": OMNIROUTE_BASE_URL,
        "omniroute_model": OMNIROUTE_MODEL,
        "omniroute_probe": probe,
        "desired_general_provider": "omniroute",
        "desired_clinical_provider": "omniroute",
        "models": models_for_roles(),
        # Backward-compatible status keys, explicitly false so clients cannot
        # claim that a direct provider is configured.
        "gemini_configured": False,
        "kimi_configured": False,
        "openrouter_configured": False,
        "bedrock_configured": False,
    }

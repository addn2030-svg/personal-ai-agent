# -*- coding: utf-8 -*-
"""Unified model router — الصحيح vs الخطأ.

الصحيح:
    response = model_router.call(
        domain="general",  # يوجه افتراضياً إلى Gemini API
        prompt=brief_prompt,
        model=os.getenv("GEMINI_MODEL", "google/gemini-3.7-flash")
    )

الخطأ:
    response = bedrock_client.converse(...)

هذا الملف هو النقطة الوحيدة المسموح لها باستدعاء bedrock-runtime مباشرة.
كل المنطق التجاري يجب أن يمر عبر model_router.call().
"""
from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any

# Re-use existing gateway for OpenRouter config & helpers
from . import model_gateway as gateway

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6").strip()
AI_MODEL_MANAGER = os.environ.get("AI_MODEL_MANAGER", "anthropic/claude-sonnet-4.6").strip()
AI_MANAGER_MODEL = os.environ.get("AI_MANAGER_MODEL", AI_MODEL_MANAGER).strip()
AI_CRITIC_MODEL = os.environ.get("AI_CRITIC_MODEL", "openai/gpt-5.6-sol").strip()
AI_GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    os.environ.get("AI_GOOGLE_MODEL", "google/gemini-3.7-flash"),
).strip()

_ROUTE = threading.local()


@dataclass
class RouterResponse:
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    provider: str = "gemini"
    fallback: bool = False

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"RouterResponse(provider={self.provider}, model={self.model}, len={len(self.text)})"


def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": provider, "model": model, "fallback": bool(fallback)}
    try:
        gateway._set_route(provider, model, fallback=fallback)
    except Exception:
        pass


def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or gateway.last_route() or {})


def _safe_error(exc: Exception) -> str:
    try:
        return gateway._safe_error(exc)
    except Exception:
        return str(exc)[:240]


def _bedrock_client():
    import boto3
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _bedrock_converse(
    *,
    model_id: str,
    system: str,
    prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    role: str = "general",
) -> RouterResponse:
    """المكان الوحيد المسموح فيه بـ bedrock_client.converse."""
    if not gateway.bedrock_configured():
        raise RuntimeError("AWS Bedrock credentials/model are not configured")
    if not model_id:
        raise RuntimeError("Bedrock model ID is empty")

    started = time.monotonic()
    kwargs: dict[str, Any] = {
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

    response = _bedrock_client().converse(**kwargs)
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    answer = "\n".join(
        str(block.get("text", "")).strip()
        for block in blocks
        if isinstance(block, dict) and block.get("text")
    ).strip()
    if not answer:
        raise RuntimeError("Bedrock model returned an empty response")

    latency = int((time.monotonic() - started) * 1000)
    _set_route("bedrock", model_id, fallback=("fallback" in role))
    return RouterResponse(
        text=answer,
        model=model_id,
        usage=dict(response.get("usage", {}) or {}),
        latency_ms=latency,
        provider="bedrock",
        fallback=("fallback" in role),
    )


def _gemini_converse(
    *,
    model_id: str,
    system: str,
    prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    chat_id: int | None = None,
    sheet_context: str = "",
    messages: list[dict] | None = None,
) -> RouterResponse:
    """Call Gemini's direct API; this is the normal primary route."""
    if not gateway.gemini_configured():
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from . import direct_specialists

    # direct_specialists is also used by the older specialist adapter. Keep its
    # key/model view synchronized with the gateway when tests or process setup
    # provide the variable after module import.
    direct_specialists.GEMINI_API_KEY = gateway.GEMINI_API_KEY
    if messages is None:
        combined_system = _bedrock_system(
            system=system,
            prompt=prompt,
            chat_id=chat_id,
            sheet_context=sheet_context,
        )
        messages, _ = _build_messages(
            system=combined_system,
            prompt=prompt,
            chat_id=chat_id,
            sheet_context="",
        )

    answer, usage, latency_ms, actual_model = direct_specialists._direct_gemini(
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
    )
    _set_route("gemini", actual_model)
    return RouterResponse(
        text=answer,
        model=actual_model,
        usage=usage,
        latency_ms=latency_ms,
        provider="gemini",
    )


def _openrouter_converse(
    *,
    model: str,
    messages: list[dict],
    sensitive: bool = False,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    response_format: dict | None = None,
) -> RouterResponse:
    answer, usage, latency_ms = gateway.openrouter_chat(
        model=model,
        messages=messages,
        sensitive=sensitive,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    route = gateway.last_route()
    actual_model = route.get("model") or model
    _set_route("openrouter", actual_model)
    return RouterResponse(
        text=answer,
        model=actual_model,
        usage=usage,
        latency_ms=latency_ms,
        provider="openrouter",
        fallback=bool(route.get("fallback")),
    )


def _build_messages(
    *,
    system: str,
    prompt: str,
    chat_id: int | None,
    sheet_context: str,
) -> tuple[list[dict], list]:
    """Build OpenAI-style messages with optional history."""
    sources: list = []
    context_block = ""

    if chat_id is not None:
        try:
            from agent_runtime import build_context, recent_messages

            ctx, src = build_context(chat_id, prompt)
            context_block = ctx
            sources = src
            if sheet_context:
                context_block += "\n\nLIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + sheet_context

            full_system = (system or "") + "\n\n" + context_block if context_block else (system or "")
            msgs: list[dict] = [{"role": "system", "content": full_system}] if full_system else []
            for row in recent_messages(chat_id)[-20:]:
                r = row.get("role")
                if r in {"user", "assistant"}:
                    msgs.append({"role": r, "content": str(row.get("content", ""))[:5000]})
            msgs.append({"role": "user", "content": str(prompt)})
            return msgs, sources
        except Exception:
            # fall through to simple builder
            pass

    # simple builder without history
    full_system = system or ""
    if sheet_context:
        full_system = (full_system + "\n\n" + sheet_context) if full_system else sheet_context
    msgs = []
    if full_system:
        msgs.append({"role": "system", "content": full_system})
    msgs.append({"role": "user", "content": str(prompt)})
    return msgs, sources


def _bedrock_system(
    *,
    system: str,
    prompt: str,
    chat_id: int | None,
    sheet_context: str,
) -> str:
    """Build the privacy-bounded context sent to the Bedrock route."""
    parts = [str(system or "").strip()]
    if chat_id is not None:
        try:
            from agent_runtime import build_context

            context, _ = build_context(chat_id, prompt)
            if context:
                parts.append(context)
        except Exception:
            # Context retrieval is best-effort; the model request remains usable.
            pass
    if sheet_context:
        parts.append("LIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + str(sheet_context))
    return "\n\n".join(part for part in parts if part)


def call(
    *,
    domain: str = "general",
    prompt: str,
    model: str | None = None,
    system: str = "",
    max_tokens: int = 1200,
    temperature: float = 0.2,
    chat_id: int | None = None,
    sheet_context: str = "",
    sensitive: bool = False,
    messages: list[dict] | None = None,
    response_format: dict | None = None,
    **kwargs,
) -> RouterResponse:
    """
    Unified entry point.

    domain:
      - "general" / "manager" / "critic" -> Gemini API by default
      - "clinical" / "sensitive" -> Gemini API by default; explicit legacy
        provider overrides remain available for compatibility
      - "bedrock" -> explicit Claude/Bedrock compatibility route
      - any other -> general behavior

    Returns RouterResponse (str() gives text).
    """
    domain = (domain or "general").strip().lower()

    clinical_domain = domain in {"clinical", "bedrock", "sensitive"} or sensitive
    provider = (
        "bedrock" if domain == "bedrock"
        else gateway.desired_provider(sensitive=clinical_domain)
    )
    # Preserve the old clinical policy semantics: an explicit clinical
    # OpenRouter override first attempts Bedrock, then may use its opt-in fallback.
    if clinical_domain and provider == "openrouter":
        provider = "bedrock"

    # Resolve model default per domain. A selected provider must never receive a
    # model slug for a different provider.
    if model is None:
        if provider == "gemini":
            model = AI_GEMINI_MODEL
        elif clinical_domain:
            model = BEDROCK_MODEL_ID
        elif domain == "manager":
            model = AI_MANAGER_MODEL
        elif domain == "critic":
            model = AI_CRITIC_MODEL
        else:
            model = os.getenv("AI_MODEL_MANAGER", AI_MANAGER_MODEL) or AI_MANAGER_MODEL
    if provider == "gemini" and not str(model).startswith(("gemini", "google/")):
        model = AI_GEMINI_MODEL
    elif provider == "bedrock" and not clinical_domain:
        model = BEDROCK_MODEL_ID

    model = str(model).strip()

    # Gemini is the only normal route and has no silent Bedrock/OpenRouter
    # fallback. This also covers clinical questions when AI_CLINICAL_PROVIDER is
    # set to its normal value, gemini.
    if provider == "gemini":
        return _gemini_converse(
            model_id=model,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            chat_id=chat_id,
            sheet_context=sheet_context,
            messages=messages,
        )

    # Explicit Bedrock compatibility path - with fallback to OpenRouter only
    # when the old clinical policy explicitly requests it.
    if clinical_domain and provider == "bedrock":
        try:
            return _bedrock_converse(
                model_id=model,
                system=_bedrock_system(
                    system=system,
                    prompt=prompt,
                    chat_id=chat_id,
                    sheet_context=sheet_context,
                ),
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                role=domain,
            )
        except Exception as exc:
            # Keep the privacy boundary: clinical fallback is available only after
            # an explicit AI_CLINICAL_PROVIDER=openrouter opt-in. The default is
            # Bedrock-only, so missing Bedrock credentials cannot silently leak the
            # case to another provider.
            err_text = str(exc).lower()
            is_access_denied = any(
                x in err_text
                for x in ("accessdenied", "explicit deny", "not authorized", "forbidden", "unauthorized")
            )
            if (
                is_access_denied
                and gateway.AI_CLINICAL_PROVIDER == "openrouter"
                and gateway.configured()
            ):
                try:
                    if messages is None:
                        messages, _ = _build_messages(
                            system=system, prompt=prompt, chat_id=chat_id, sheet_context=sheet_context
                        )
                    # استخدم نموذج OpenRouter للـ fallback
                    fallback_model = os.getenv("AI_MODEL_MANAGER", AI_MODEL_MANAGER) or AI_MANAGER_MODEL
                    result = _openrouter_converse(
                        model=fallback_model,
                        messages=messages,
                        sensitive=False,  # fallback to general policy
                        max_tokens=max_tokens,
                        temperature=temperature,
                        response_format=response_format,
                    )
                    result.fallback = True
                    return result
                except Exception:
                    pass
            raise

    # Explicit Claude/Bedrock compatibility route.
    if provider == "bedrock":
        return _bedrock_converse(
            model_id=BEDROCK_MODEL_ID,
            system=_bedrock_system(
                system=system,
                prompt=prompt,
                chat_id=chat_id,
                sheet_context=sheet_context,
            ),
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            role=domain,
        )

    # Legacy explicit OpenRouter path. The normal Gemini route never reaches
    # this branch and never falls back here.
    try:
        if messages is None:
            messages, _ = _build_messages(
                system=system, prompt=prompt, chat_id=chat_id, sheet_context=sheet_context
            )
        return _openrouter_converse(
            model=model,
            messages=messages,
            sensitive=sensitive,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
    except Exception as exc:
        # Fallback to Bedrock only if allowed and configured
        if gateway.OPENROUTER_FALLBACK_BEDROCK and gateway.bedrock_configured():
            try:
                fb_model = BEDROCK_MODEL_ID
                combined_system = _bedrock_system(
                    system=system,
                    prompt=prompt,
                    chat_id=chat_id,
                    sheet_context=sheet_context,
                )
                return _bedrock_converse(
                    model_id=fb_model,
                    system=combined_system,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    role=f"{domain}-fallback",
                )
            except Exception:
                pass
        raise


# Convenience: return just text
def call_text(**kwargs) -> str:
    return call(**kwargs).text


# For backward compatibility with older imports
def ask(*args, **kwargs):
    """Legacy wrapper returning 4-tuple like model_gateway.ask."""
    chat_id = kwargs.get("chat_id") or (args[0] if args else None)
    text = kwargs.get("text") or (args[1] if len(args) > 1 else "")
    system_prompt = kwargs.get("system_prompt", "")
    sheet_context = kwargs.get("sheet_context", "")
    sensitive = kwargs.get("sensitive", False)
    result = call(
        domain="clinical" if sensitive else "general",
        prompt=text,
        system=system_prompt,
        chat_id=chat_id,
        sheet_context=sheet_context,
        sensitive=sensitive,
    )
    # build_context sources if possible
    sources = []
    if chat_id is not None:
        try:
            from agent_runtime import build_context

            _, sources = build_context(chat_id, text)
        except Exception:
            pass
    return result.text, result.usage, result.latency_ms, sources

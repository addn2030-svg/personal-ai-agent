# -*- coding: utf-8 -*-
"""Provider diagnostics overlay for specialist routing.

The direct-specialist adapter intentionally falls back to OpenRouter. This overlay
preserves the original Gemini direct error when both the direct API and OpenRouter
fallback fail, so Telegram reports the actionable Google-side cause instead of only
an OpenRouter credit error.
"""
from __future__ import annotations

from . import direct_specialists as direct

GEMINI_API_KEY = direct.GEMINI_API_KEY


def combined_provider_error(provider: str, direct_error: Exception, fallback_error: Exception) -> RuntimeError:
    direct_text = str(direct_error)[:320]
    fallback_text = str(fallback_error)[:180]
    return RuntimeError(
        f"{provider} direct failed: {direct_text}; OpenRouter fallback failed: {fallback_text}"
    )


def install(gateway) -> None:
    """Wrap the already-installed specialist router with failure diagnostics."""
    if getattr(gateway, "_provider_diagnostics_installed", False):
        return

    original_chat = gateway.openrouter_chat

    def routed_chat(*, model: str, messages: list[dict], sensitive: bool = False,
                    max_tokens: int = 1200, temperature: float = 0.2,
                    response_format: dict | None = None):
        if (
            not sensitive
            and response_format is None
            and model.startswith("google/")
            and GEMINI_API_KEY
        ):
            try:
                answer, usage, latency_ms, actual_model = direct._direct_gemini(
                    model=model, messages=messages, max_tokens=max_tokens
                )
                gateway._set_route("gemini", actual_model)
                return answer, usage, latency_ms
            except Exception as direct_error:
                try:
                    return original_chat(
                        model=model,
                        messages=messages,
                        sensitive=sensitive,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        response_format=response_format,
                    )
                except Exception as fallback_error:
                    raise combined_provider_error(
                        "Gemini", direct_error, fallback_error
                    ) from fallback_error

        return original_chat(
            model=model,
            messages=messages,
            sensitive=sensitive,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )

    gateway.openrouter_chat = routed_chat
    gateway._provider_diagnostics_installed = True

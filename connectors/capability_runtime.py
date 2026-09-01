# -*- coding: utf-8 -*-
"""Install runtime capability truth without changing Telegram/webhook architecture."""
from __future__ import annotations

from connectors import capability_truth

_INSTALLED = False


def install():
    global _INSTALLED
    if _INSTALLED:
        return

    from connectors import model_gateway as models
    from connectors import telegram_bot_legacy as legacy

    original_ask = models.ask

    def grounded_ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
                     sensitive: bool = False, bedrock_fallback=None):
        truth = capability_truth.prompt_context(text)
        combined = sheet_context or ""
        if truth:
            combined = (truth + "\n\n" + combined).strip()
        result = original_ask(
            chat_id,
            text,
            system_prompt=system_prompt,
            sheet_context=combined,
            sensitive=sensitive,
            bedrock_fallback=bedrock_fallback,
        )
        answer, usage, latency_ms, sources = result
        guarded = capability_truth.guard_response(text, answer)
        if guarded != answer and "capability_truth" not in sources:
            sources = list(sources) + ["capability_truth"]
        return guarded, usage, latency_ms, sources

    # One authoritative privacy classifier is used by routing, logging/redaction,
    # intake classification, and webhook data minimization.  This prevents generic
    # professional phrases such as "physical therapy" from being treated as a
    # patient record.
    legacy._clinical_hint = capability_truth.clinical_private
    models.ask = grounded_ask
    _INSTALLED = True

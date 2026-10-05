# -*- coding: utf-8 -*-
"""Compatibility router: every model inference is delegated to OmniRoute."""
from __future__ import annotations
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any
from . import model_gateway as gateway

AI_MANAGER_MODEL = gateway.OMNIROUTE_MANAGER_MODEL
AI_CRITIC_MODEL = gateway.OMNIROUTE_CRITIC_MODEL
AI_GEMINI_MODEL = gateway.OMNIROUTE_MODEL
BEDROCK_MODEL_ID = gateway.OMNIROUTE_MODEL
_ROUTE = threading.local()

@dataclass
class RouterResponse:
    text: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    provider: str = "omniroute"
    fallback: bool = False
    def __str__(self): return self.text
    def __repr__(self): return f"RouterResponse(provider={self.provider}, model={self.model}, len={len(self.text)})"

def _set_route(provider: str, model: str, fallback: bool = False):
    _ROUTE.value = {"provider": "omniroute", "model": model, "fallback": bool(fallback)}
    gateway._set_route("omniroute", model, fallback)

def last_route() -> dict:
    return dict(getattr(_ROUTE, "value", {}) or gateway.last_route())

def _safe_error(exc: Exception) -> str:
    return gateway._safe_error(exc)

def _build_messages(*, system: str, prompt: str, chat_id: int | None, sheet_context: str):
    sources = []
    context = ""
    if chat_id is not None:
        try:
            from agent_runtime import build_context, recent_messages
            context, sources = build_context(chat_id, prompt)
            if sheet_context: context += "\n\nLIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + sheet_context
            messages = [{"role": "system", "content": (system + "\n\n" + context).strip()}]
            for row in recent_messages(chat_id)[-20:]:
                if row.get("role") in {"user", "assistant"}:
                    messages.append({"role": row["role"], "content": str(row.get("content", ""))[:5000]})
            messages.append({"role": "user", "content": str(prompt)})
            return messages, sources
        except Exception:
            pass
    messages = []
    content = system or ""
    if sheet_context: content = (content + "\n\n" + sheet_context).strip()
    if content: messages.append({"role": "system", "content": content})
    messages.append({"role": "user", "content": str(prompt)})
    return messages, sources

def _bedrock_system(*, system: str, prompt: str, chat_id: int | None, sheet_context: str) -> str:
    messages, _ = _build_messages(system=system, prompt=prompt, chat_id=chat_id, sheet_context=sheet_context)
    return "\n\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")

def _omniroute(*, model: str, messages: list[dict], sensitive: bool = False, max_tokens: int = 1200,
               temperature: float = 0.2, response_format: dict | None = None) -> RouterResponse:
    answer, usage, latency = gateway.openrouter_chat(model=model, messages=messages, sensitive=sensitive,
        max_tokens=max_tokens, temperature=temperature, response_format=response_format)
    actual = gateway.last_route().get("model") or model
    _set_route("omniroute", actual)
    return RouterResponse(answer, actual, usage, latency)

def _bedrock_converse(*, model_id: str, system: str, prompt: str, max_tokens: int = 1200,
                      temperature: float = 0.2, role: str = "general") -> RouterResponse:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return _omniroute(model=model_id or gateway.OMNIROUTE_MODEL, messages=messages,
                      max_tokens=max_tokens, temperature=temperature)

def _gemini_converse(*, model_id: str, system: str, prompt: str, max_tokens: int = 1200,
                     temperature: float = 0.2, chat_id: int | None = None, sheet_context: str = "",
                     messages: list[dict] | None = None) -> RouterResponse:
    if messages is None: messages, _ = _build_messages(system=system, prompt=prompt, chat_id=chat_id, sheet_context=sheet_context)
    return _omniroute(model=model_id or gateway.OMNIROUTE_MODEL, messages=messages,
                      max_tokens=max_tokens, temperature=temperature)

def call(*, domain: str = "general", prompt: str, model: str | None = None, system: str = "",
         max_tokens: int = 1200, temperature: float = 0.2, chat_id: int | None = None,
         sheet_context: str = "", sensitive: bool = False, messages: list[dict] | None = None,
         response_format: dict | None = None, **kwargs) -> RouterResponse:
    selected = model or (gateway.OMNIROUTE_MANAGER_MODEL if domain == "manager" else
                         gateway.OMNIROUTE_CRITIC_MODEL if domain == "critic" else gateway.OMNIROUTE_MODEL)
    if not messages:
        messages, _ = _build_messages(system=system, prompt=prompt, chat_id=chat_id, sheet_context=sheet_context)
    return _omniroute(model=selected, messages=messages, sensitive=sensitive,
                      max_tokens=max_tokens, temperature=temperature, response_format=response_format)

def call_text(**kwargs) -> str:
    return call(**kwargs).text

def ask(*args, **kwargs):
    chat_id = kwargs.get("chat_id") or (args[0] if args else None)
    prompt = kwargs.get("text") or (args[1] if len(args) > 1 else "")
    result = call(domain="clinical" if kwargs.get("sensitive") else "general", prompt=prompt,
        system=kwargs.get("system_prompt", ""), chat_id=chat_id, sheet_context=kwargs.get("sheet_context", ""),
        sensitive=kwargs.get("sensitive", False))
    sources = []
    if chat_id is not None:
        try:
            from agent_runtime import build_context
            _, sources = build_context(chat_id, prompt)
        except Exception: pass
    return result.text, result.usage, result.latency_ms, sources

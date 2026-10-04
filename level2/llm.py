# -*- coding: utf-8 -*-
"""
جسر نموذج لغوي — اختياري تمامًا (Optional).

الوضع الافتراضي: بلا أي نموذج ولا مفتاح — المدير يعمل بالبروتوكولات الحتمية.
عند الرغبة في محادثة أغنى، اضبط متغيرات بيئة توافق OpenAI-compatible:

    LLM_BASE_URL=http://localhost:11434/v1   # Ollama محلي (مجاني، بلا إنترنت)
    LLM_BASE_URL=https://...                 # أو OmniRoute أو أي مزود متوافق
    LLM_API_KEY=...                          # (Ollama لا يحتاجه)
    LLM_MODEL=...                            # مثل qwen3:8b أو أي نموذج متاح

لا اعتماد إلزامي على أي مزود: فشل النداء ⇒ رجوع تلقائي للرد الحتمي.
"""
from __future__ import annotations

import json
import os
import urllib.request

TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "45"))


def config() -> dict:
    return {
        "base_url": (os.environ.get("LLM_BASE_URL") or "").strip().rstrip("/"),
        "api_key": (os.environ.get("LLM_API_KEY") or "").strip(),
        "model": (os.environ.get("LLM_MODEL") or "").strip(),
    }


def enabled() -> bool:
    c = config()
    return bool(c["base_url"] and c["model"])


def status() -> dict:
    c = config()
    return {
        "enabled": enabled(),
        "base_url": c["base_url"] or None,
        "model": c["model"] or None,
        "mode": "LLM" if enabled() else "OFFLINE_DETERMINISTIC",
    }


def chat(system: str, user: str, history: list[dict] | None = None) -> str | None:
    """أرسل محادثة إلى نقطة نهاية متوافقة مع OpenAI. يرجع النص أو None عند الفشل."""
    if not enabled():
        return None
    c = config()
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-6:]:
        if h.get("user"):
            messages.append({"role": "user", "content": h["user"]})
        if h.get("agent"):
            messages.append({"role": "assistant", "content": h["agent"]})
    messages.append({"role": "user", "content": user})

    body = json.dumps({
        "model": c["model"],
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 700,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{c['base_url']}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {c['api_key']}"} if c["api_key"] else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:
        # فشل الشبكة/المزود لا يُسقط المدير: المتصل يرجع للرد الحتمي
        return None

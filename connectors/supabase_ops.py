# -*- coding: utf-8 -*-
"""مِراء تشغيلية إلى Supabase — الكتابة المزدوجة بجانب Google Sheets.

مبدأ (وفق قرار 2026-11-02):
- الاتجاه واحد: التطبيق ──يكتب──▶ Supabase (مرآة) — لا كتابة يدوية.
- فشل الكتابة إلى Supabase لا يعطّل شيئًا: fail-soft، يُطبع التحذير فقط.
- الجداول: agent_intake (مدخلات الوكيل) و agent_conversations (محادثات الوكيل)
  أنشئت في supabase/03_operational_mirrors.sql.
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

_client_cache = None


def enabled() -> bool:
    return os.environ.get("SUPABASE_WRITE_ENABLED", "0").strip().lower() in {"1", "true", "yes"}


def _client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    from connectors.supabase_client import SupabaseClient, load_config
    _client_cache = SupabaseClient(load_config())
    return _client_cache


def save_intake_row(*, intake_id: str, occurred_at: str, source: str,
                    chat_user_id: str, input_type: str, raw_message: str,
                    language: str = "", classification: str = "",
                    privacy: str = "NORMAL", status: str = "",
                    response_id: str = "", processed_at: str = "",
                    error: str = "") -> bool:
    """يدفع صف مدخلة واحدة إلى agent_intake. يعيد False عند أي فشل."""
    try:
        _client().insert("agent_intake", [{
            "intake_id": str(intake_id)[:120],
            "occurred_at": occurred_at,
            "source": str(source or "TELEGRAM")[:40],
            "chat_user_id": str(chat_user_id)[:64] if chat_user_id else None,
            "input_type": str(input_type)[:40] if input_type else None,
            "raw_message": str(raw_message)[:8000] if raw_message else None,
            "language": str(language)[:12] if language else None,
            "classification": str(classification)[:64] if classification else None,
            "privacy": str(privacy)[:24] if privacy else None,
            "status": str(status)[:24] if status else None,
            "response_id": str(response_id)[:120] if response_id else None,
            "processed_at": processed_at or None,
            "error": str(error)[:1000] if error else None,
            "sync_run": "live",
        }], returning=False)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft حسب التصميم
        print(f"Supabase intake mirror error: {str(exc)[:180]}", flush=True)
        return False


def save_conversation_row(*, conversation_id: str, intake_id: str,
                          occurred_at: str, provider: str, model_id: str,
                          question: str, answer: str, input_tokens="",
                          output_tokens="", duration_ms="", status: str = "",
                          human_approval: str = "NOT_REQUIRED", error: str = "") -> bool:
    """يدفع صف محادثة واحدة إلى agent_conversations. يعيد False عند أي فشل."""
    def _num(v):
        try:
            return int(float(str(v))) if str(v).strip() else None
        except (TypeError, ValueError):
            return None

    try:
        _client().insert("agent_conversations", [{
            "conversation_id": str(conversation_id)[:120],
            "intake_id": str(intake_id)[:120] if intake_id else None,
            "occurred_at": occurred_at,
            "provider": str(provider)[:40] if provider else None,
            "model": str(model_id)[:120] if model_id else None,
            "question": str(question)[:8000] if question else None,
            "answer": str(answer)[:8000] if answer else None,
            "input_tokens": _num(input_tokens),
            "output_tokens": _num(output_tokens),
            "duration_ms": _num(duration_ms),
            "status": str(status)[:24] if status else None,
            "human_approval": str(human_approval)[:24] if human_approval else None,
            "sync_run": "live",
        }], returning=False)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Supabase conversation mirror error: {str(exc)[:180]}", flush=True)
        return False
# -*- coding: utf-8 -*-
"""Minimal runtime truth guard for configured Google Sheets access.

This hotfix is intentionally narrow and reversible. It fixes a proven production
failure where the model says the configured Main Sheet cannot be read even though
the agent has a working Sheets connector. It does not claim arbitrary Google Sheet
URLs are supported, and it never claims a mutation succeeded without a receipt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHEET_RE = re.compile(
    r"google\s*sheets?|spreadsheet|main\s+sheet|financial\s+sheet|\bsheets?\b|"
    r"شيت|شيتات|جدول|جداول|الجدول|الشيت",
    re.I,
)
_FALSE_DENIAL_RE = re.compile(
    r"(?:cannot|can't|can\s*not|unable\s+to).*?(?:open|read|access).*?(?:sheet|spreadsheet)|"
    r"no\s+(?:active\s+)?google\s+sheets\s+api\s+connection|"
    r"no\s+live\s+internet\s+access|"
    r"لا\s+أستطيع.*?(?:فتح|قراءة|الوصول).*?(?:شيت|جدول)|"
    r"لا\s+يوجد.*?(?:اتصال|ربط).*?(?:google\s*sheets|شيت|جدول)",
    re.I | re.S,
)


@dataclass(frozen=True)
class SheetCapability:
    configured: bool
    read_verified: bool
    write_route: bool
    title: str
    tab_count: int
    error: str = ""


def sheet_related(text: str) -> bool:
    return bool(_SHEET_RE.search(text or ""))


def probe() -> SheetCapability:
    """Read-only runtime probe. No mutation is performed."""
    try:
        from connectors import sheet_intelligence as sheets

        configured = bool(sheets.configured())
        if not configured:
            return SheetCapability(False, False, False, "", 0, "not configured")
        metadata = sheets.metadata()
        titles = [str(row.get("title") or "").strip() for row in metadata if row.get("title")]
        write_route = bool(sheets._direct_ready() or sheets._webhook_ready())
        # The connector is configured to one canonical workbook via GOOGLE_SHEET_ID.
        # A successful metadata request proves live read access to that workbook.
        return SheetCapability(True, True, write_route, "configured main workbook", len(titles), "")
    except Exception as exc:  # connector boundary
        return SheetCapability(True, False, False, "", 0, f"{type(exc).__name__}: {str(exc)[:180]}")


def _truth_context(cap: SheetCapability) -> str:
    return (
        "RUNTIME GOOGLE SHEETS TRUTH — authoritative:\n"
        f"- Configured main workbook: {'YES' if cap.configured else 'NO'}\n"
        f"- Live metadata read verified now: {'YES' if cap.read_verified else 'NO'}\n"
        f"- Write route available: {'YES' if cap.write_route else 'NO'}\n"
        f"- Live tab count: {cap.tab_count}\n"
        "- Do NOT say the configured Main Sheet is inaccessible when live read is verified.\n"
        "- Do NOT claim arbitrary Google Sheets URLs are supported; the current connector targets the configured workbook.\n"
        "- For writes: proposal -> preview -> approval -> execution -> receipt.\n"
        "- Never claim a write succeeded without a concrete receipt."
        + (f"\n- Probe error: {cap.error}" if cap.error else "")
    )


def _correct_false_denial(answer: str, cap: SheetCapability) -> str:
    if not (cap.read_verified and _FALSE_DENIAL_RE.search(answer or "")):
        return answer
    write = (
        "يوجد أيضًا مسار كتابة، لكن أي تعديل يبقى خلف المعاينة والموافقة ثم إيصال التنفيذ."
        if cap.write_route
        else "القراءة مؤكدة، بينما مسار الكتابة غير متحقق في هذه اللحظة."
    )
    return (
        "✅ تصحيح قدرة الوكيل: الشيت الرئيسي المهيأ متصل فعليًا الآن عبر Google Sheets API، "
        f"وتم التحقق من القراءة الحية ({cap.tab_count} تبويب). {write}\n\n"
        "لا أحتاج منك لصق بيانات الشيت الرئيسي يدويًا. إذا أعطيتني رابط شيت آخر غير الشيت المهيأ، "
        "فلن أفترض أن لدي صلاحية عليه حتى يتم التحقق منه."
    )


def install() -> None:
    """Wrap the model gateway once; no Telegram/webhook architecture change."""
    from connectors import model_gateway as models

    if getattr(models, "_sheet_capability_hotfix_installed", False):
        return
    original_ask = models.ask

    def grounded_ask(chat_id: int, text: str, *, system_prompt: str, sheet_context: str = "",
                     sensitive: bool = False, bedrock_fallback=None):
        cap = probe() if sheet_related(text) else None
        combined = sheet_context or ""
        if cap is not None:
            combined = (_truth_context(cap) + "\n\n" + combined).strip()
        answer, usage, latency_ms, sources = original_ask(
            chat_id,
            text,
            system_prompt=system_prompt,
            sheet_context=combined,
            sensitive=sensitive,
            bedrock_fallback=bedrock_fallback,
        )
        if cap is not None:
            corrected = _correct_false_denial(answer, cap)
            if corrected != answer:
                answer = corrected
                sources = list(sources or [])
                if "sheet_capability_hotfix" not in sources:
                    sources.append("sheet_capability_hotfix")
        return answer, usage, latency_ms, sources

    models.ask = grounded_ask
    models._sheet_capability_hotfix_installed = True

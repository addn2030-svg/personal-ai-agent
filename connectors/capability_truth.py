# -*- coding: utf-8 -*-
"""Runtime-grounded capability truth for Abdulrahman AI OS.

The language model must never guess what the agent can access or mutate.  This
module derives a bounded capability packet from the actual runtime and supplies a
deterministic answer for vague Sheet/memory sync requests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_ACTION_RE = re.compile(
    r"\b(update|sync|save|write|store|remember|refresh)\b|"
    r"حد[ثّ]|تحديث|زامن|احفظ|حفظ|سجل|سجّل|تذكر|ذاكر[ةه]",
    re.I,
)
_SHEET_RE = re.compile(r"sheet|sheets|spreadsheet|google\s*sheet|شيت|شيتات|جدول|جداول", re.I)
_MEMORY_RE = re.compile(r"memory|remember|ذاكر[ةه]|تذكر|احفظ", re.I)

# Require actual clinical/patient context. Generic professional phrases such as
# "physical therapy / العلاج الطبيعي" alone are NOT private clinical content.
_CLINICAL_STRONG_RE = re.compile(
    r"\bpatient\b|\bmrn\b|medical\s*record|diagnosis|symptom|"
    r"رقم\s*الملف|رقم\s*الهوية|المريض|مريض|تشخيص|عرض\s*مرضي",
    re.I,
)
_CLINICAL_PAIN_RE = re.compile(
    r"\b(my|his|her|patient'?s)\s+(pain|injury|surgery|symptoms?)\b|"
    r"ألمي|ألمه|ألمها|إصابتي|اصابتي|إصابته|عملية\s+(?:لي|للمريض)",
    re.I,
)

_FALSE_SHEET_DENIAL_RE = re.compile(
    r"(?:i\s+)?(?:can\s*not|cannot|can't)\s+(?:directly\s+)?(?:write|access).*?(?:sheet|spreadsheet)|"
    r"لا\s+أستطيع.*?(?:الكتابة|الوصول).*?(?:شيت|جدول)",
    re.I | re.S,
)


@dataclass(frozen=True)
class CapabilitySnapshot:
    sheet_configured: bool
    sheet_read_verified: bool
    sheet_write_route: bool
    sheet_tabs: tuple[str, ...]
    sheet_error: str = ""

    @property
    def tab_count(self) -> int:
        return len(self.sheet_tabs)


def clinical_private(text: str) -> bool:
    """Conservative privacy classifier; avoids false positives on profession names."""
    value = text or ""
    return bool(_CLINICAL_STRONG_RE.search(value) or _CLINICAL_PAIN_RE.search(value))


def action_related(text: str) -> bool:
    value = text or ""
    return bool(_ACTION_RE.search(value) and (_SHEET_RE.search(value) or _MEMORY_RE.search(value)))


def sheet_memory_sync_request(text: str) -> bool:
    value = text or ""
    return bool(_ACTION_RE.search(value) and _SHEET_RE.search(value) and _MEMORY_RE.search(value))


def snapshot() -> CapabilitySnapshot:
    """Read capability truth from the live connector; never infer successful writes."""
    try:
        from connectors import sheet_intelligence as sheets

        configured = bool(sheets.configured())
        if not configured:
            return CapabilitySnapshot(False, False, False, ())
        rows = sheets.metadata()
        titles = tuple(str(row.get("title", "")).strip() for row in rows if row.get("title"))
        # A configured direct or authenticated-webhook route exposes update_cell().
        # This means a write route exists; a concrete write is only successful after
        # its own receipt and is never inferred from this flag.
        write_route = bool(sheets._direct_ready() or sheets._webhook_ready())
        return CapabilitySnapshot(True, True, write_route, titles)
    except Exception as exc:  # fail closed
        return CapabilitySnapshot(True, False, False, (), f"{type(exc).__name__}: {str(exc)[:160]}")


def prompt_context(text: str) -> str:
    """Inject verified capability facts only when the request concerns actions/state."""
    if not action_related(text):
        return ""
    cap = snapshot()
    tabs = ", ".join(cap.sheet_tabs[:24]) if cap.sheet_tabs else "NONE_VERIFIED"
    return (
        "RUNTIME CAPABILITY TRUTH — authoritative, do not contradict:\n"
        f"- Google Sheets configured: {'YES' if cap.sheet_configured else 'NO'}\n"
        f"- Google Sheets live read verified this request: {'YES' if cap.sheet_read_verified else 'NO'}\n"
        f"- Google Sheets write route available: {'YES' if cap.sheet_write_route else 'NO'}\n"
        f"- Live tab count: {cap.tab_count}\n"
        f"- Live tab names: {tabs}\n"
        "- Authorized Telegram messages and responses use an automatic logging path.\n"
        "- Conversation memory has an automatic StateStore write path for the current runtime.\n"
        "- Durable semantic memory exists, but promoting a durable fact requires review/approval.\n"
        "- Never claim a specific Sheet or durable-memory mutation succeeded without a concrete receipt.\n"
        "- Operational mutation rule: proposal -> preview -> approval -> execution -> receipt.\n"
        "- Never invent a tab, cell, project, owner, date, fact, or receipt. Unknown = NEEDS_INPUT."
        + (f"\n- Capability probe error: {cap.sheet_error}" if cap.sheet_error else "")
    )


def direct_preflight_response(text: str) -> str | None:
    """Deterministic response for vague combined Sheet+memory sync requests.

    A phrase like "update the sheets information and memory" contains no exact
    mutation payload.  The correct action is to prove connectivity and ask one
    blocking question, not hallucinate rows/projects/dates.
    """
    if not sheet_memory_sync_request(text):
        return None
    cap = snapshot()
    if cap.sheet_read_verified:
        sheet_line = f"✅ Google Sheets: live read verified — {cap.tab_count} tabs."
    elif cap.sheet_configured:
        sheet_line = "⚠️ Google Sheets: configured, but the live read probe failed."
    else:
        sheet_line = "❌ Google Sheets: no configured route detected."

    write_line = (
        "✅ Sheet write route exists, but each business-data mutation stays preview/approval/receipt gated."
        if cap.sheet_write_route else
        "⚠️ No verified Sheet write route is available right now."
    )
    return (
        "🧠 ACTION PREFLIGHT\n"
        + sheet_line + "\n"
        + write_line + "\n"
        "✅ Conversation memory: automatic runtime save path is enabled.\n"
        "✅ Durable semantic memory: supported; promotion requires review before it becomes a durable fact.\n\n"
        "I will not invent tab names, dates, owners, or facts. I also will not claim a write until I have its receipt.\n\n"
        "NEEDS_INPUT: Which exact information from the conversation should be promoted into operational Sheets/durable memory?\n"
        "Once identified, I will produce one preview, then execute only after approval and return the destination/receipt."
    )


def guard_response(text: str, answer: str) -> str:
    """Prevent a model from contradicting a verified Sheet capability."""
    if not action_related(text):
        return answer
    cap = snapshot()
    if cap.sheet_read_verified and _FALSE_SHEET_DENIAL_RE.search(answer or ""):
        direct = direct_preflight_response(text)
        if direct:
            return direct
        return (
            "⚠️ Capability correction: Google Sheets live access is verified for this runtime. "
            "I can read the connected workbook and a write route is available when approved. "
            "I will not claim a mutation succeeded without a receipt.\n\n"
            + (answer or "")
        )
    return answer

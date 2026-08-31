# -*- coding: utf-8 -*-
"""Runtime-grounded capability truth for Abdulrahman AI OS.

The model must never guess which tools exist. This module derives capability facts
from the running connectors and corrects blanket denials such as "I am text-only".
Unsupported capabilities (browser checkout/payment) are also stated explicitly so
the agent does not overclaim.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

_ACTION_RE = re.compile(
    r"\b(update|sync|save|write|store|remember|refresh|execute|order|buy|purchase)\b|"
    r"حد[ثّ]|تحديث|زامن|احفظ|حفظ|سجل|سجّل|تذكر|ذاكر[ةه]|نفذ|نفّذ|اطلب|اشتري|شراء",
    re.I,
)
_SHEET_RE = re.compile(r"sheet|sheets|spreadsheet|google\s*sheet|شيت|شيتات|جدول|جداول", re.I)
_MEMORY_RE = re.compile(r"memory|remember|ذاكر[ةه]|تذكر|احفظ", re.I)
_CAPABILITY_RE = re.compile(
    r"can\s+you|are\s+you\s+(?:able|text)|tools?|browser|open\s+(?:a\s+)?site|"
    r"outside\s+(?:the\s+)?conversation|agent\s+framework|checkout|payment|order|buy|purchase|"
    r"هل\s+(?:تستطيع|يمكنك)|تستطيع|يمكنك|أدوات|ادوات|متصفح|افتح\s+موقع|فتح\s+موقع|"
    r"خارج\s+المحادثة|نظام\s+نصي|وكيل\s+مفوض|إطار\s+عمل|اطلب|شراء|دفع",
    re.I,
)
_SHOPPING_RE = re.compile(r"order|buy|purchase|checkout|payment|اطلب|اشتري|شراء|دفع|منظفات|amazon|noon|نون|أمازون", re.I)

# Require actual patient/clinical context. Generic professional phrases such as
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
_FALSE_BLANKET_DENIAL_RE = re.compile(
    r"text[- ]?only|no\s+external\s+tools|cannot\s+act\s+outside|can't\s+act\s+outside|"
    r"لا\s+أملك\s+أدوات\s+تنفيذ|لا\s+أتصرف\s+خارج\s+المحادثة|نظام\s+نصي\s+فقط|"
    r"لا\s+أكمل\s+طلبات",
    re.I | re.S,
)


@dataclass(frozen=True)
class CapabilitySnapshot:
    sheet_configured: bool
    sheet_read_verified: bool
    sheet_write_route: bool
    sheet_tabs: tuple[str, ...]
    sheet_error: str = ""
    calendar_tools_implemented: bool = True
    calendar_read_verified: bool = False
    calendar_write_route: bool = False
    calendar_error: str = ""
    telegram_configured: bool = False
    conversation_memory: bool = True
    durable_memory: bool = True
    browser_tool: bool = False
    checkout_tool: bool = False
    payment_tool: bool = False
    agent_runtime: bool = True

    @property
    def tab_count(self) -> int:
        return len(self.sheet_tabs)

    @property
    def has_external_tools(self) -> bool:
        return bool(
            self.sheet_read_verified
            or self.sheet_write_route
            or self.calendar_read_verified
            or self.calendar_write_route
            or self.telegram_configured
        )


def clinical_private(text: str) -> bool:
    value = text or ""
    return bool(_CLINICAL_STRONG_RE.search(value) or _CLINICAL_PAIN_RE.search(value))


def capability_related(text: str) -> bool:
    return bool(_CAPABILITY_RE.search(text or ""))


def action_related(text: str) -> bool:
    value = text or ""
    return bool(
        capability_related(value)
        or (_ACTION_RE.search(value) and (_SHEET_RE.search(value) or _MEMORY_RE.search(value)))
    )


def sheet_memory_sync_request(text: str) -> bool:
    value = text or ""
    return bool(_ACTION_RE.search(value) and _SHEET_RE.search(value) and _MEMORY_RE.search(value))


def _calendar_probe() -> tuple[bool, bool, str]:
    """Read-only Calendar connectivity probe; never creates/deletes an event."""
    try:
        from connectors import calendar_actions as calendar
        calendar.list_events(days_forward=1, max_results=1)
        # The same Calendar service is used by create_event/delete_event, but writes
        # remain approval gated in Telegram. A read success proves the service route.
        return True, True, ""
    except Exception as exc:
        return False, False, f"{type(exc).__name__}: {str(exc)[:160]}"


def snapshot() -> CapabilitySnapshot:
    """Read capability truth from actual connectors; never infer a completed action."""
    sheet_configured = False
    sheet_read = False
    sheet_write = False
    titles: tuple[str, ...] = ()
    sheet_error = ""
    try:
        from connectors import sheet_intelligence as sheets
        sheet_configured = bool(sheets.configured())
        if sheet_configured:
            rows = sheets.metadata()
            titles = tuple(str(row.get("title", "")).strip() for row in rows if row.get("title"))
            sheet_read = True
            sheet_write = bool(sheets._direct_ready() or sheets._webhook_ready())
    except Exception as exc:
        sheet_error = f"{type(exc).__name__}: {str(exc)[:160]}"

    calendar_read, calendar_write, calendar_error = _calendar_probe()
    return CapabilitySnapshot(
        sheet_configured=sheet_configured,
        sheet_read_verified=sheet_read,
        sheet_write_route=sheet_write,
        sheet_tabs=titles,
        sheet_error=sheet_error,
        calendar_tools_implemented=True,
        calendar_read_verified=calendar_read,
        calendar_write_route=calendar_write,
        calendar_error=calendar_error,
        telegram_configured=bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
    )


def prompt_context(text: str) -> str:
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
        f"- Google Calendar tooling implemented: {'YES' if cap.calendar_tools_implemented else 'NO'}\n"
        f"- Google Calendar live read verified: {'YES' if cap.calendar_read_verified else 'NO'}\n"
        f"- Google Calendar write route verified: {'YES' if cap.calendar_write_route else 'NO'}\n"
        f"- Telegram bot route configured: {'YES' if cap.telegram_configured else 'NO'}\n"
        "- Conversation memory has an automatic StateStore write path.\n"
        "- Durable semantic memory exists; promotion of durable facts requires review/approval.\n"
        "- Browser/web-navigation tool in this Telegram runtime: NO.\n"
        "- Retail checkout tool: NO.\n"
        "- Payment tool: NO.\n"
        "- The existing Python runtime already is the agent orchestration framework; LangChain/CrewAI/Assistants API are optional, not prerequisites.\n"
        "- Never make a blanket claim that the agent is text-only or has no external tools when verified connectors exist.\n"
        "- Never claim a specific mutation/purchase succeeded without a concrete receipt.\n"
        "- External mutation rule: proposal -> preview -> approval -> execution -> receipt.\n"
        "- Never invent a tab, cell, project, owner, date, product result, purchase, or receipt. Unknown = NEEDS_INPUT."
        + (f"\n- Sheets probe error: {cap.sheet_error}" if cap.sheet_error else "")
        + (f"\n- Calendar probe error: {cap.calendar_error}" if cap.calendar_error else "")
    )


def direct_preflight_response(text: str) -> str | None:
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
        "🧠 ACTION PREFLIGHT\n" + sheet_line + "\n" + write_line + "\n"
        "✅ Conversation memory: automatic runtime save path is enabled.\n"
        "✅ Durable semantic memory: supported; promotion requires review before it becomes a durable fact.\n\n"
        "I will not invent tab names, dates, owners, or facts. I also will not claim a write until I have its receipt.\n\n"
        "NEEDS_INPUT: Which exact information from the conversation should be promoted into operational Sheets/durable memory?\n"
        "Once identified, I will produce one preview, then execute only after approval and return the destination/receipt."
    )


def capability_summary_response(text: str) -> str:
    """Deterministic truthful answer to tool/autonomy questions."""
    cap = snapshot()
    arabic = bool(re.search(r"[\u0600-\u06FF]", text or ""))
    shopping = bool(_SHOPPING_RE.search(text or ""))
    if arabic:
        lines = [
            "🧭 حالة القدرات الفعلية",
            f"✅ Google Sheets: {'قراءة مباشرة مؤكدة' if cap.sheet_read_verified else 'غير مؤكدة الآن'}؛ {'مسار كتابة موجود خلف الموافقة' if cap.sheet_write_route else 'لا يوجد مسار كتابة مؤكد الآن'}.",
            f"✅ Google Calendar: {'القراءة/المسار متحقق' if cap.calendar_read_verified else 'الأداة موجودة لكن الاتصال الحي غير متحقق الآن'}؛ أي كتابة تبقى خلف المعاينة والموافقة.",
            f"✅ Telegram: {'متصل' if cap.telegram_configured else 'غير مثبت من البيئة الحالية'}؛ المحادثات تُسجل عبر المسار الحالي.",
            "✅ الذاكرة: ذاكرة محادثة تلقائية + ذاكرة دائمة بمراجعة قبل ترقية الحقائق.",
            "❌ Browser/تصفح مواقع المتاجر: غير موجود في Runtime الحالي.",
            "❌ Checkout/Payment: غير موجودين؛ لذلك لا أستطيع إتمام شراء أو دفع الآن.",
            "✅ لا نحتاج LangChain أو CrewAI لكي أصبح وكيلاً؛ Runtime Python الحالي هو إطار الوكيل بالفعل، ويمكن إضافة أدوات إليه مباشرة.",
        ]
        if shopping:
            lines.append("النتيجة: أستطيع إدارة البحث/القرار والبيانات ضمن الأدوات المتصلة، لكن إتمام طلب متجر فعلي يحتاج Browser/Commerce connector منفصلًا، ثم يبقى الشراء خلف موافقة صريحة وإيصال.")
        return "\n".join(lines)

    lines = [
        "🧭 VERIFIED CAPABILITY STATUS",
        f"✅ Google Sheets: {'live read verified' if cap.sheet_read_verified else 'not live-verified now'}; {'write route exists behind approval' if cap.sheet_write_route else 'no verified write route now'}.",
        f"✅ Google Calendar: {'live route verified' if cap.calendar_read_verified else 'tooling exists but live connectivity is not verified now'}; writes remain preview/approval gated.",
        f"✅ Telegram: {'configured' if cap.telegram_configured else 'not proven by the current environment'}.",
        "✅ Memory: automatic conversation memory plus review-gated durable semantic memory.",
        "❌ Browser/retail site navigation: not implemented in this Telegram runtime.",
        "❌ Checkout/payment: not implemented, so I cannot complete or pay for an online purchase yet.",
        "✅ LangChain/CrewAI/Assistants API are not required; the existing Python runtime already provides the agent orchestration layer.",
    ]
    if shopping:
        lines.append("Result: I can manage supported operational actions now, but a real retail order requires a separate browser/commerce connector and explicit approval before purchase.")
    return "\n".join(lines)


def guard_response(text: str, answer: str) -> str:
    if not action_related(text):
        return answer
    cap = snapshot()
    if cap.sheet_read_verified and _FALSE_SHEET_DENIAL_RE.search(answer or ""):
        direct = direct_preflight_response(text)
        if direct:
            return direct
        return capability_summary_response(text)
    if cap.has_external_tools and _FALSE_BLANKET_DENIAL_RE.search(answer or ""):
        return capability_summary_response(text)
    return answer

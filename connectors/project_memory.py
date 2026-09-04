# -*- coding: utf-8 -*-
"""Google Drive project-memory connector.

Reads the project's Status/Progress/Decision Google Docs and applies only
human-confirmed updates. GitHub remains the source of truth for code.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass

from connectors import google_credentials

DOC_IDS = {
    "status": os.environ.get("PROJECT_MEMORY_STATUS_DOC_ID", "1zs5GJ5Kw9TgHpNAfTOo37Fo7TnQYXejgquXOtHTQCuE"),
    "progress": os.environ.get("PROJECT_MEMORY_PROGRESS_DOC_ID", "1WolECTe7H3L7ZMRrsjrVzhZ7twXi_ZixvQgJkAu9G3w"),
    "decision": os.environ.get("PROJECT_MEMORY_DECISION_DOC_ID", "1g_Vz042YHXlCKwDJnat-WVEKVhPp6oNQ4Be-7ZC3BJA"),
}
_APPROVAL_TTL = 15 * 60
_LOCK = threading.Lock()
_PENDING: dict[str, "MemoryUpdate"] = {}
_SERVICE = None
_SENSITIVE = re.compile(
    r"(api[_ -]?key|token|secret|password|كلمة مرور|رمز وصول|رقم الهوية|رقم الملف|اسم المريض)",
    re.I,
)


@dataclass(frozen=True)
class MemoryUpdate:
    achievement: str
    next_step: str
    decision: str
    created_at: float


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON غير مهيأ")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/documents"],
    )
    _SERVICE = build("docs", "v1", credentials=credentials, cache_discovery=False)
    return _SERVICE


def _text(document: dict) -> str:
    lines = []
    for item in (document.get("body") or {}).get("content", []):
        paragraph = item.get("paragraph")
        if not paragraph:
            continue
        for element in paragraph.get("elements", []):
            run = element.get("textRun")
            if run:
                lines.append(run.get("content", ""))
    return "".join(lines).strip()


def read_memory(max_chars: int = 2500) -> str:
    parts = ["🧠 ذاكرة المشروع — Google Drive"]
    for key, label in (("status", "الحالة"), ("progress", "آخر سجل تقدم"), ("decision", "القرارات")):
        document = _service().documents().get(documentId=DOC_IDS[key]).execute()
        value = _text(document)
        if key == "progress" and len(value) > 900:
            value = value[-900:]
        else:
            value = value[:900]
        parts.extend(["", f"【{label}】", value or "غير معروف"])
    return "\n".join(parts)[:max_chars]


def _clean(value: str, limit: int = 1200) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def prepare(raw: str) -> tuple[str, str]:
    """Prepare: achievement || next step || optional decision."""
    pieces = [p.strip() for p in str(raw or "").split("||", 2)]
    achievement = _clean(pieces[0] if pieces else "")
    next_step = _clean(pieces[1] if len(pieces) > 1 else "غير معروف")
    decision = _clean(pieces[2] if len(pieces) > 2 else "")
    combined = " ".join((achievement, next_step, decision))
    if not achievement:
        raise ValueError("اكتب: /update_memory الإنجاز || الخطوة التالية || القرار الاختياري")
    if _SENSITIVE.search(combined):
        raise ValueError("رفض التحديث: قد يحتوي أسراراً أو بيانات مرضى. أزلها ثم أعد المحاولة.")
    created = time.time()
    digest = hashlib.sha256(
        f"{achievement}|{next_step}|{decision}|{created}".encode("utf-8")
    ).hexdigest()[:10]
    with _LOCK:
        _expire_locked(created)
        _PENDING[digest] = MemoryUpdate(achievement, next_step, decision, created)
    preview = (
        "📝 معاينة تحديث ذاكرة المشروع\n"
        f"الإنجاز: {achievement}\n"
        f"الخطوة التالية: {next_step}\n"
        f"القرار: {decision or 'لا يوجد قرار جديد'}\n\n"
        f"للتنفيذ خلال 15 دقيقة: /confirm_memory {digest}"
    )
    return digest, preview


def _expire_locked(now: float):
    for key, value in list(_PENDING.items()):
        if now - value.created_at > _APPROVAL_TTL:
            _PENDING.pop(key, None)


def _append(document_id: str, value: str):
    document = _service().documents().get(documentId=document_id).execute()
    content = (document.get("body") or {}).get("content") or []
    end_index = int(content[-1].get("endIndex", 1)) - 1 if content else 1
    _service().documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": max(1, end_index)}, "text": value}}]},
    ).execute()


def confirm(digest: str) -> str:
    now = time.time()
    with _LOCK:
        _expire_locked(now)
        update = _PENDING.pop(str(digest or "").strip(), None)
    if not update:
        raise ValueError("رمز التأكيد غير صالح أو انتهت مدته. أنشئ معاينة جديدة.")
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="minutes")
    progress = (
        f"\n\nالتاريخ: {stamp}\nالإنجاز\n{update.achievement}\n"
        f"الخطوة التالية\n{update.next_step}\n"
        "المصدر\nتحديث مؤكد من Telegram.\n"
    )
    status = (
        f"\n\nآخر تحديث مؤكد: {stamp}\n"
        f"ما تم إنجازه\n{update.achievement}\n"
        f"الخطوة التالية\n{update.next_step}\n"
    )
    _append(DOC_IDS["progress"], progress)
    _append(DOC_IDS["status"], status)
    changed = ["Progress.md", "Status.md"]
    if update.decision:
        decision = (
            f"\n\nالتاريخ: {stamp}\nالقرار\n{update.decision}\n"
            "لماذا اتخذناه\nغير معروف — يحتاج استكمالاً.\n"
            "البدائل\nغير معروفة.\nالحالة\nنشط.\n"
        )
        _append(DOC_IDS["decision"], decision)
        changed.append("Decision.md")
    return "✅ تم تحديث ذاكرة المشروع: " + "، ".join(changed)


def status_text() -> str:
    configured = bool(google_credentials.service_account_info())
    return (
        "🧠 Project Memory\n"
        f"Google credentials: {'configured ✅' if configured else 'not configured ❌'}\n"
        "Mode: read + preview + confirmed write\n"
        "Approval TTL: 15 minutes"
    )

# -*- coding: utf-8 -*-
"""Guarded Google Docs project memory for Abdulrahman AI OS.

The project memory is deliberately split into three durable Google Docs:
Status.md, Progress.md, and Decision.md. Reads are allowed directly. Writes are
preview -> explicit Telegram confirmation and are idempotent per confirmation
 token.
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

TZ = dt.timezone(dt.timedelta(hours=3))
DOC_IDS = {
    "status": os.environ.get(
        "PROJECT_MEMORY_STATUS_DOC_ID",
        "1zs5GJ5Kw9TgHpNAfTOo37Fo7TnQYXejgquXOtHTQCuE",
    ).strip(),
    "progress": os.environ.get(
        "PROJECT_MEMORY_PROGRESS_DOC_ID",
        "1WolECTe7H3L7ZMRrsjrVzhZ7twXi_ZixvQgJkAu9G3w",
    ).strip(),
    "decision": os.environ.get(
        "PROJECT_MEMORY_DECISION_DOC_ID",
        "1g_Vz042YHXlCKwDJnat-WVEKVhPp6oNQ4Be-7ZC3BJA",
    ).strip(),
}

_APPROVAL_TTL_SECONDS = max(
    60, int(os.environ.get("PROJECT_MEMORY_APPROVAL_TTL_SECONDS", "900"))
)
_LOCK = threading.Lock()
_SERVICE = None

_SENSITIVE = re.compile(
    r"(api[_ -]?key|token|secret|password|bearer|كلمة\s*مرور|رمز\s*وصول|"
    r"رقم\s*الهوية|رقم\s*الملف|اسم\s*المريض|mrn|patient\s*name)",
    re.I,
)


@dataclass(frozen=True)
class MemoryUpdate:
    achievement: str
    next_step: str
    decision: str
    created_at: float


_PENDING: dict[str, MemoryUpdate] = {}


def _service_account_info() -> dict:
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON غير مهيأ أو غير صالح")
    return info


def service_account_email() -> str:
    try:
        return str(_service_account_info().get("client_email") or "unknown")
    except Exception:
        return "unknown"


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = _service_account_info()
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/documents"],
    )
    _SERVICE = build("docs", "v1", credentials=credentials, cache_discovery=False)
    return _SERVICE


def _text(document: dict) -> str:
    chunks: list[str] = []
    for item in (document.get("body") or {}).get("content", []):
        paragraph = item.get("paragraph")
        if not paragraph:
            continue
        for element in paragraph.get("elements", []):
            run = element.get("textRun")
            if run:
                chunks.append(run.get("content", ""))
    return "".join(chunks).strip()


def _document(key: str) -> dict:
    document_id = DOC_IDS.get(key, "")
    if not document_id:
        raise RuntimeError(f"PROJECT_MEMORY_{key.upper()}_DOC_ID غير مضبوط")
    return _service().documents().get(documentId=document_id).execute()


def diagnose() -> dict:
    result = {
        "configured": bool(google_credentials.service_account_info()),
        "service_account": service_account_email(),
        "docs": {},
        "ok": False,
    }
    if not result["configured"]:
        result["error"] = "GOOGLE_SERVICE_ACCOUNT_JSON غير مهيأ"
        return result

    all_ok = True
    for key in ("status", "progress", "decision"):
        try:
            doc = _document(key)
            result["docs"][key] = {
                "ok": True,
                "id": DOC_IDS[key],
                "title": doc.get("title") or key,
            }
        except Exception as exc:  # external Google boundary
            all_ok = False
            result["docs"][key] = {
                "ok": False,
                "id": DOC_IDS[key],
                "error": str(exc).replace("\n", " ")[:220],
            }
    result["ok"] = all_ok
    return result


def status_text() -> str:
    diag = diagnose()
    lines = [
        "🧠 Project Memory — Google Drive",
        f"Service account: {diag.get('service_account', 'unknown')}",
        f"Credentials: {'configured ✅' if diag.get('configured') else 'not configured ❌'}",
    ]
    labels = {"status": "Status.md", "progress": "Progress.md", "decision": "Decision.md"}
    for key in ("status", "progress", "decision"):
        item = (diag.get("docs") or {}).get(key) or {}
        lines.append(f"{labels[key]}: {'readable ✅' if item.get('ok') else 'unavailable ❌'}")
        if not item.get("ok") and item.get("error"):
            lines.append("  " + str(item["error"])[:180])
    lines.extend([
        "Mode: read + preview + confirmed write",
        f"Approval TTL: {_APPROVAL_TTL_SECONDS // 60} minutes",
    ])
    if not diag.get("ok"):
        lines.append("إذا ظهر 403/404: شارك المستندات الثلاثة مع Service account أعلاه بصلاحية Editor.")
    return "\n".join(lines)


def read_memory(max_chars: int = 3200) -> str:
    parts = ["🧠 ذاكرة المشروع — Google Drive"]
    specs = (
        ("status", "الحالة الحالية", 950, False),
        ("progress", "آخر التقدم", 1100, True),
        ("decision", "القرارات", 950, True),
    )
    for key, label, limit, tail in specs:
        value = _text(_document(key))
        if len(value) > limit:
            value = value[-limit:] if tail else value[:limit]
        parts.extend(["", f"【{label}】", value or "لا توجد بيانات."])
    return "\n".join(parts)[:max_chars]


def _clean(value: str, limit: int = 1200) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _expire_locked(now: float):
    for key, value in list(_PENDING.items()):
        if now - value.created_at > _APPROVAL_TTL_SECONDS:
            _PENDING.pop(key, None)


def prepare(raw: str) -> tuple[str, str]:
    """Prepare a guarded update: achievement || next step || optional decision."""
    pieces = [p.strip() for p in str(raw or "").split("||", 2)]
    achievement = _clean(pieces[0] if pieces else "")
    next_step = _clean(pieces[1] if len(pieces) > 1 else "غير محدد")
    decision = _clean(pieces[2] if len(pieces) > 2 else "")
    combined = " ".join((achievement, next_step, decision))
    if not achievement:
        raise ValueError("اكتب: /update_memory الإنجاز || الخطوة التالية || القرار الاختياري")
    if _SENSITIVE.search(combined):
        raise ValueError("رفض التحديث: قد يحتوي سرًا أو بيانات مريض. أزلها ثم أعد المحاولة.")

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
        f"للتنفيذ خلال {_APPROVAL_TTL_SECONDS // 60} دقيقة: /confirm_memory {digest}"
    )
    return digest, preview


def _append_once(document_id: str, marker: str, value: str) -> bool:
    """Append only if marker is absent; returns True when a write occurred."""
    service = _service()
    document = service.documents().get(documentId=document_id).execute()
    current = _text(document)
    if marker in current:
        return False
    content = (document.get("body") or {}).get("content") or []
    end_index = int(content[-1].get("endIndex", 1)) - 1 if content else 1
    service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": max(1, end_index)},
                        "text": value,
                    }
                }
            ]
        },
    ).execute()
    return True


def confirm(digest: str) -> str:
    token = str(digest or "").strip()
    now = time.time()
    with _LOCK:
        _expire_locked(now)
        update = _PENDING.get(token)
    if not update:
        raise ValueError("رمز التأكيد غير صالح أو انتهت مدته. أنشئ معاينة جديدة.")

    stamp = dt.datetime.now(TZ).isoformat(timespec="minutes")
    marker = f"[memory:{token}]"
    progress = (
        f"\n\n{marker}\nالتاريخ: {stamp}\nالإنجاز\n{update.achievement}\n"
        f"الخطوة التالية\n{update.next_step}\nالمصدر\nتحديث مؤكد من Telegram.\n"
    )
    status = (
        f"\n\n{marker}\nآخر تحديث مؤكد: {stamp}\nما تم إنجازه\n{update.achievement}\n"
        f"الخطوة التالية\n{update.next_step}\n"
    )

    changed: list[str] = []
    if _append_once(DOC_IDS["progress"], marker, progress):
        changed.append("Progress.md")
    if _append_once(DOC_IDS["status"], marker, status):
        changed.append("Status.md")

    if update.decision:
        decision = (
            f"\n\n{marker}\nالتاريخ: {stamp}\nالقرار\n{update.decision}\n"
            "لماذا اتخذناه\nيُستكمل عند الحاجة.\nالبدائل\nيُستكمل عند الحاجة.\nالحالة\nنشط.\n"
        )
        if _append_once(DOC_IDS["decision"], marker, decision):
            changed.append("Decision.md")

    with _LOCK:
        _PENDING.pop(token, None)

    if changed:
        return "✅ تم تحديث ذاكرة المشروع: " + "، ".join(changed)
    return "✅ هذا التحديث موجود مسبقًا في الذاكرة؛ لم تتم كتابة نسخة مكررة."

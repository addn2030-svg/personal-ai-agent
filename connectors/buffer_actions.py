# -*- coding: utf-8 -*-
"""Buffer post actions behind the human approval gate (C2).

/buffer_post from Telegram creates a PENDING_APPROVAL action in the unified
action queue (Store.action_queue). Nothing leaves the system until the owner
approves: the Telegram ✅ button (or engine/approve.py) then publishes through
connectors.buffer_publisher (Buffer GraphQL API) and the action is closed as
EXECUTED with a receipt. On failure the action returns to PENDING_APPROVAL
with the recorded error, so the owner can retry after fixing the cause.

Usage (Telegram):
  /buffer_post instagram | نص المنشور
  /buffer_post instagram | نص المنشور | https://raw.githubusercontent.com/.../image.jpg
  /buffer_post linkedin | نص المنشور | 2026-09-12 18:00 | مسودة

The first field is the Buffer service name (instagram/linkedin/...) or an
explicit channel id (from /buffer_channels). Extra fields after the text are
optional and order-free: image URL (http...), schedule time (YYYY-MM-DD HH:MM,
Riyadh time), and "draft"/"مسودة" to save as a Buffer draft instead of queueing.

Never stores or prints BUFFER_API_KEY.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets

from connectors import buffer_publisher
from engine.store import Store, log_event

TZ_OFFSET = buffer_publisher.DEFAULT_TZ_OFFSET  # "+03:00" — توقيت السعودية
MAX_TEXT_CHARS = 5000
_DUE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})$")
_URL_RE = re.compile(r"^https?://\S+$", re.I)
_DRAFT_WORDS = {"draft", "مسودة", "مسوده"}

USAGE = (
    "الصيغة: /buffer_post القناة | نص المنشور [| رابط صورة] [| YYYY-MM-DD HH:MM] [| مسودة]\n"
    "مثال: /buffer_post instagram | ملخص كتاب هذا الأسبوع… | https://raw.githubusercontent.com/.../cover.jpg\n"
    "القناة = اسم الشبكة (instagram/linkedin/…) أو معرف القناة من /buffer_channels\n"
    "الوقت بتوقيت السعودية · «مسودة» تحفظ كمسودة في Buffer بدل الطابور"
)


def _today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date().isoformat()


def parse_request(raw: str) -> dict:
    """Parses the /buffer_post payload into a bounded, deterministic dict."""
    parts = [p.strip() for p in (raw or "").split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("NEEDS_INPUT: " + USAGE)

    channel, text = parts[0], parts[1]
    if len(channel) > 120:
        raise ValueError("معرّف القناة طويل جدًا (الحد 120 حرفًا).")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"نص المنشور طويل جدًا (الحد {MAX_TEXT_CHARS} حرفًا).")

    image_url: str | None = None
    due_at: str | None = None
    draft = False
    for extra in parts[2:]:
        if not extra:
            continue
        if _URL_RE.match(extra):
            if image_url:
                raise ValueError("رابط صورة واحد فقط مسموح.")
            image_url = extra
        elif extra.lower() in _DRAFT_WORDS:
            draft = True
        elif _DUE_RE.match(extra):
            if due_at:
                raise ValueError("وقت جدولة واحد فقط مسموح.")
            try:
                dt.datetime.strptime(extra.replace("T", " "), "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError("وقت الجدولة غير صالح: " + extra) from None
            due_at = extra
        else:
            raise ValueError(
                "حقل غير مفهوم: «" + extra[:80] + "» — الحقول الإضافية: رابط صورة أو وقت (YYYY-MM-DD HH:MM) أو «مسودة»."
            )

    return {"channel": channel, "text": text, "image_url": image_url,
            "due_at": due_at, "draft": draft}


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_content(payload: dict) -> str:
    """Queue-UI text (approvals page, /approve) for a Buffer post action."""
    mode = "مسودة في Buffer" if payload.get("draft") else "طابور Buffer التلقائي"
    if payload.get("due_at"):
        mode = f"جدولة {payload['due_at']} (توقيت السعودية)"
    lines = [
        f"[Buffer] القناة: {payload['channel']} · الوضع: {mode}",
        "النص:",
        payload["text"],
    ]
    if payload.get("image_url"):
        lines.append("الصورة: " + payload["image_url"])
    return "\n".join(lines)


def create_action(payload: dict, *, chat_id: int | str = "", store: Store | None = None) -> dict:
    """Enqueues a BUFFER_POST action as PENDING_APPROVAL (idempotent by hash)."""
    digest = _payload_hash(payload)

    def add_action(state):
        queue = state.setdefault("action_queue", [])
        for existing in queue:
            if (existing.get("type") == "BUFFER_POST"
                    and existing.get("content_hash") == digest
                    and existing.get("status") in ("PENDING_APPROVAL", "APPROVED", "EXECUTED")):
                return False, existing  # idempotency — لا تكرار لما هو قائم/منفّذ
        record = {
            "action_id": "BP-" + secrets.token_hex(4).upper(),
            "type": "BUFFER_POST",
            "channel": "buffer",
            "status": "PENDING_APPROVAL",
            "content": render_content(payload),
            "content_hash": digest,
            "created_at": _today(),
            "expires_at": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
            "approved_at": None,
            "executed_at": None,
            "payload": dict(payload),
            "source": f"telegram:{chat_id}" if chat_id != "" else "api",
        }
        queue.append(record)
        return True, record

    st = store or Store()
    record = st.transaction(add_action, "buffer_post_enqueue")
    log_event("action_enqueued", action_id=record["action_id"], hash=digest, type="BUFFER_POST")
    return record


def preview_keyboard(record: dict) -> dict:
    """Standard approval-gate inline keyboard bound to the content hash (C2)."""
    aid, h8 = record["action_id"], record["content_hash"][:8]
    return {"inline_keyboard": [[
        {"text": f"✅ اعتماد ونشر {aid}", "callback_data": f"ap:{aid}:{h8}"},
        {"text": f"❌ رفض {aid}", "callback_data": f"rj:{aid}"},
    ]]}


def preview_text(record: dict) -> str:
    payload = record["payload"]
    mode = "مسودة تُحفظ في Buffer (بلا نشر)" if payload.get("draft") else "إضافة إلى طابور Buffer التلقائي"
    if payload.get("due_at"):
        mode = f"جدولة في {payload['due_at']} بتوقيت السعودية"
    lines = [
        "📮 مسودة منشور Buffer — لم يُنشر بعد (خلف بوابة الاعتماد)",
        f"القناة: {payload['channel']}",
        "النص:",
        payload["text"],
    ]
    if payload.get("image_url"):
        lines.append("الصورة: " + payload["image_url"])
    lines += [
        f"الوضع عند الاعتماد: {mode}",
        f"الإجراء: {record['action_id']} · البصمة: {record['content_hash'][:8]} · الصلاحية: 48 ساعة",
        "",
        "للنشر: زر الاعتماد أدناه — لا يخرج أي أثر خارجي قبل موافقتك.",
    ]
    return "\n".join(lines)


def resolve_channel(channel_ref: str) -> tuple[str, str]:
    """Resolves a service name (or explicit id) to (channel_id, label).

    Validates against the account's live channel list first so a typo can
    never post to a wrong target. Raises RuntimeError with a safe message.
    """
    ref = (channel_ref or "").strip()
    if not ref:
        raise RuntimeError("NEEDS_INPUT: حدد القناة (اسم الشبكة أو معرف القناة).")
    try:
        channels = buffer_publisher.get_channels()
    except SystemExit as exc:  # buffer_publisher يرفع SystemExit — لا يجوز أن يوقف البوت
        raise RuntimeError(str(exc)) from exc
    if not channels:
        raise RuntimeError("لا توجد قنوات مرتبطة بمفتاح Buffer — اربط قناة من publish.buffer.com أولًا.")
    for ch in channels:
        if str(ch.get("id") or "") == ref:
            label = ch.get("displayName") or ch.get("name") or ch.get("service") or ref
            return ref, f"{label} ({ch.get('service')})"
    matches = [c for c in channels if str(c.get("service") or "").lower() == ref.lower()]
    if not matches:
        available = ", ".join(sorted({str(c.get("service")) for c in channels}))
        raise RuntimeError(
            f"لا توجد قناة باسم «{ref}». الشبكات المتصلة: {available or 'لا شيء'} — جرّب /buffer_channels"
        )
    active = [c for c in matches if not c.get("isQueuePaused")]
    chosen = active[0] if active else matches[0]
    label = chosen.get("displayName") or chosen.get("name") or chosen.get("service")
    return str(chosen["id"]), f"{label} ({chosen.get('service')})"


def _plain_str(value) -> str:
    """Store round-trips date-like strings into date/datetime objects — coerce back."""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def execute(record: dict) -> dict:
    """Publishes the approved action via Buffer. Returns the created post."""
    payload = record.get("payload") or {}
    channel_id, _label = resolve_channel(_plain_str(payload.get("channel", "")))
    text = _plain_str(payload.get("text", ""))
    image_url = payload.get("image_url")
    due_at = payload.get("due_at")
    try:
        return buffer_publisher.create_post(
            channel_id=channel_id,
            text=text,
            image_url=_plain_str(image_url) if image_url else None,
            due_at=_plain_str(due_at) if due_at else None,
            draft=bool(payload.get("draft")),
            tz_offset=TZ_OFFSET,
        )
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc


def maybe_execute(action_id: str, *, store: Store | None = None) -> dict | None:
    """Executes an APPROVED BUFFER_POST action; other actions → None.

    Success → EXECUTED + receipt. Failure → back to PENDING_APPROVAL with the
    error recorded (retryable after fixing the cause, still inside the gate).
    """
    st = store or Store()
    rows = st.rows_all()
    action = next((a for a in rows.get("action_queue", [])
                   if a.get("action_id") == action_id), None)
    if not action or action.get("type") != "BUFFER_POST" or action.get("status") != "APPROVED":
        return None

    try:
        post = execute(action)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:400]

        def revert(state):
            row = next((a for a in state.get("action_queue", [])
                        if a.get("action_id") == action_id), None)
            if row and row.get("status") == "APPROVED":
                row["status"] = "PENDING_APPROVAL"
                row["approved_at"] = None
                row["last_error"] = err
                return True, row
            return False, row

        st.transaction(revert, "buffer_post_failed", action_id=action_id, error=err[:200])
        log_event("buffer_post_failed", action_id=action_id, error=err[:200])
        return {"ok": False, "action_id": action_id, "error": err}

    post_id = str(post.get("id") or "")
    post_status = str(post.get("status") or "")

    def finalize(state):
        row = next((a for a in state.get("action_queue", [])
                    if a.get("action_id") == action_id), None)
        if not row or row.get("status") != "APPROVED":
            return False, row
        row["status"] = "EXECUTED"
        row["executed_at"] = _today()
        row["post_id"] = post_id
        row["post_status"] = post_status
        return True, row

    st.transaction(finalize, "buffer_post_executed", action_id=action_id, post_id=post_id)
    log_event("action_executed", action_id=action_id, post_id=post_id, via="buffer")
    return {"ok": True, "action_id": action_id, "post": post}


def receipt_text(outcome: dict) -> str:
    record_id = outcome.get("action_id", "")
    if not outcome.get("ok"):
        return ("❌ تعذر نشر " + record_id + ": " + str(outcome.get("error", ""))[:300] +
                "\nأُعيد الإجراء إلى بانتظار الاعتماد — عالج السبب ثم اضغط الاعتماد مرة أخرى.")
    post = outcome.get("post") or {}
    status_ar = {"scheduled": "مجدول", "draft": "مسودة", "queued": "في الطابور"}.get(
        str(post.get("status", "")), str(post.get("status", "")))
    return ("📤 نُشر عبر Buffer ✅\n"
            f"الإجراء: {record_id} — EXECUTED\n"
            f"Post ID: {post.get('id', '—')} · الحالة: {status_ar or '—'}")

# -*- coding: utf-8 -*-
"""Approval-gated multi-agent content workflow for Buffer.

Models research angles, criticise claims, and create platform copy. They never
publish. A selected draft is persisted in StateStore and only an explicit
approval code may call the Buffer connector.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
from typing import Callable

from connectors import buffer_publisher
from connectors.task_delegation import contains_private_data
from engine.store import Store, log_event

DEFAULT_PLATFORM = os.environ.get("CONTENT_DEFAULT_PLATFORM", "linkedin").strip().lower()
DEFAULT_MODE = os.environ.get("BUFFER_DEFAULT_MODE", "draft").strip().lower()
ALLOWED_MODES = {"draft", "queue", "schedule"}
ALLOWED_PLATFORMS = {
    "linkedin", "instagram", "facebook", "twitter", "x", "threads",
    "tiktok", "youtube", "pinterest", "bluesky",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _json_object(text: str) -> dict:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Content Creator did not return valid JSON")
    parsed = json.loads(value[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Content Creator result must be an object")
    return parsed


def _bounded(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _normalise(result: dict, idea: str, platform: str) -> dict:
    copy = _bounded(result.get("copy"), 3000)
    if not copy:
        raise ValueError("Content Creator returned empty copy")
    hashtags = result.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    return {
        "platform": platform,
        "goal": _bounded(result.get("goal") or idea, 300),
        "audience": _bounded(result.get("audience") or "professional audience", 200),
        "hook": _bounded(result.get("hook"), 300),
        "copy": copy,
        "cta": _bounded(result.get("cta"), 300),
        "hashtags": [_bounded(x, 80) for x in hashtags[:12] if str(x).strip()],
        "image_brief": _bounded(result.get("image_brief"), 700),
        "claims_to_verify": [_bounded(x, 300) for x in (result.get("claims_to_verify") or [])[:8]],
    }


def _field_from_packet(packet: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+)$", packet or "")
    return match.group(1).strip() if match else ""


def _safe_fallback(idea: str, platform: str) -> dict:
    """Build a reviewable draft when a low-credit model truncates its JSON.

    Sheet packets already contain approved source copy.  For free-form `/content`
    requests we use the supplied idea itself.  This fallback never invents facts.
    """
    sheet_copy = _field_from_packet(idea, "Caption_AR") or _field_from_packet(idea, "Caption_EN")
    copy = sheet_copy or (idea if "QUEUE ITEM " not in idea else _field_from_packet(idea, "Post_Title"))
    copy = _bounded(copy, 2200)
    if not copy:
        raise ValueError("Creator output was incomplete and the source row has no usable caption")
    tags = _field_from_packet(idea, "Hashtags").split()
    return {
        "platform": platform,
        "goal": _bounded(_field_from_packet(idea, "Post_Title") or "reviewed content draft", 300),
        "audience": "Life Pulse audience",
        "hook": _bounded(_field_from_packet(idea, "Hook_AR"), 300),
        "copy": copy,
        "cta": _bounded(_field_from_packet(idea, "CTA_AR"), 300),
        "hashtags": [_bounded(x, 80) for x in tags[:12]],
        "image_brief": _bounded(_field_from_packet(idea, "Cover_Text"), 700),
        "claims_to_verify": ["AI JSON was incomplete; source-sheet copy used — review before approval"],
    }


def create_content_preview(
    idea: str,
    *,
    chat_id: int,
    model_call: Callable[[str, str], str],
    platform: str | None = None,
    mode: str | None = None,
    due_at: str | None = None,
    image_url: str | None = None,
) -> dict:
    idea = (idea or "").strip()
    if not idea:
        raise ValueError("NEEDS_INPUT: write the content idea after /content")
    if contains_private_data(idea):
        raise ValueError("Remove patient names, record numbers, phone numbers, and private identifiers.")
    platform = (platform or DEFAULT_PLATFORM).lower()
    mode = (mode or DEFAULT_MODE).lower()
    if platform not in ALLOWED_PLATFORMS:
        raise ValueError("Unsupported platform: " + platform)
    if mode not in ALLOWED_MODES:
        raise ValueError("Mode must be draft, queue, or schedule")
    if mode == "schedule" and not due_at:
        raise ValueError("NEEDS_INPUT: schedule mode requires --at YYYY-MM-DD HH:MM")

    try:
        research = model_call(
            "researcher",
            "Generate a compact content-angle packet for the idea below. Separate known facts from assumptions. "
            "Do not claim live research or invent statistics, sources, testimonials, or patient stories. Include audience, "
            "pain points, three angles, and evidence gaps.\n\nIDEA:\n" + idea,
        )
    except Exception as exc:
        research = "Research specialist unavailable; use only the user's supplied idea. Error: " + type(exc).__name__
    try:
        critique = model_call(
            "critic",
            "Audit this content packet for unsupported clinical/marketing claims, privacy, reputation risk, weak logic, "
            "and platform fit. Return corrections and a recommended angle. Do not add new facts.\n\n"
            + research[:7000],
        )
    except Exception as exc:
        critique = "Critic unavailable; creator must use conservative claims. Error: " + type(exc).__name__
    final = model_call(
        "creator",
        "Create one polished post for Abdulrahman's Life Pulse professional brand. Keep medical language educational, "
        "never diagnostic or guaranteed. Use the supplied research and critique only. Return JSON only with keys: "
        "goal, audience, hook, copy, cta, hashtags (array), image_brief, claims_to_verify (array). "
        f"Platform: {platform}.\n\nIDEA:\n{idea}\n\nRESEARCH:\n{research[:6000]}\n\nCRITIQUE:\n{critique[:5000]}",
    )
    try:
        content = _normalise(_json_object(final), idea, platform)
    except (ValueError, json.JSONDecodeError):
        content = _safe_fallback(idea, platform)
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    action_id = "CONTENT-" + secrets.token_hex(4).upper()
    row = {
        "action_id": action_id,
        "type": "CONTENT_BUFFER_POST",
        "status": "PENDING_APPROVAL",
        "approval_code": digest[:10].upper(),
        "content_hash": digest,
        "content": content["copy"],
        "content_plan": content,
        "platform": platform,
        "mode": mode,
        "due_at": due_at,
        "image_url": image_url,
        "created_at": _now(),
        "expires_at": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
        "approved_at": None,
        "executed_at": None,
        "receipts": [],
        "origin": "content_creator_orchestra",
        "chat_id": str(chat_id),
    }

    def add(state):
        state.setdefault("action_queue", []).append(row)
        return True, row

    Store().transaction(add, "content_preview_created", action_id=action_id, platform=platform)
    log_event("content_preview_created", action_id=action_id, platform=platform, mode=mode)
    return row


def render_preview(row: dict) -> str:
    plan = row["content_plan"]
    tags = " ".join(plan.get("hashtags") or [])
    claims = plan.get("claims_to_verify") or []
    return "\n".join([
        "✍️ Content Creator — PREVIEW",
        f"Platform: {row['platform']} | Buffer mode: {row['mode']}",
        f"Hook: {plan.get('hook') or '—'}",
        "",
        plan["copy"],
        ("\n" + tags) if tags else "",
        "",
        f"CTA: {plan.get('cta') or '—'}",
        f"Image brief: {plan.get('image_brief') or '—'}",
        "Claims to verify: " + (" | ".join(claims) if claims else "none ✅"),
        "",
        "Nothing has been sent to Buffer.",
        f"Approve: /approve_content {row['action_id']} {row['approval_code']}",
        f"Reject: /reject_content {row['action_id']}",
    ])[:3900]


def execute(action_id: str, approval_code: str) -> dict:
    if str(action_id or "").strip().upper() in {"CONTENT-ID", "ID"} or str(
        approval_code or ""
    ).strip().upper() == "CODE":
        raise ValueError(
            "Create a preview first with /content_sheet Q-001, then copy the exact "
            "/approve_content command shown at the bottom of that preview."
        )

    def claim(state):
        row = next((x for x in state.get("action_queue", []) if x.get("action_id") == action_id), None)
        if not row or row.get("type") != "CONTENT_BUFFER_POST":
            raise ValueError("Content action not found")
        if row.get("status") != "PENDING_APPROVAL":
            raise ValueError("Content action is not pending approval")
        if str(row.get("approval_code", "")).upper() != str(approval_code or "").upper():
            raise ValueError("Approval code does not match")
        if str(row.get("expires_at")) < dt.date.today().isoformat():
            row["status"] = "EXPIRED"
            return True, row
        row["status"] = "EXECUTING"
        row["approved_at"] = _now()
        return True, dict(row)

    row = Store().transaction(claim, "content_publish_claimed", action_id=action_id)
    if row.get("status") == "EXPIRED":
        raise ValueError("Content approval expired; create a fresh preview")
    if row.get("video_url"):
        def restore(state):
            target = next(x for x in state["action_queue"] if x.get("action_id") == action_id)
            target["status"] = "PENDING_APPROVAL"
            return True, dict(target)
        Store().transaction(restore, "content_video_buffer_blocked", action_id=action_id)
        raise ValueError(
            "Video is generated and saved in Drive, but this Buffer connector has not yet "
            "verified video-upload support. Nothing was published."
        )
    channel_id = buffer_publisher.resolve_channel("", row["platform"])
    post = buffer_publisher.create_post(
        channel_id=channel_id,
        text=row["content"],
        image_url=row.get("image_url"),
        due_at=row.get("due_at") if row.get("mode") == "schedule" else None,
        draft=row.get("mode") == "draft",
        tz_offset=buffer_publisher.DEFAULT_TZ_OFFSET,
    )
    receipt = {"provider": "buffer", "post_id": post.get("id"), "status": post.get("status"), "channel_id": channel_id}

    def finish(state):
        target = next(x for x in state["action_queue"] if x.get("action_id") == action_id)
        target["status"] = "EXECUTED"
        target["executed_at"] = _now()
        target["receipts"] = [receipt]
        return True, dict(target)

    Store().transaction(finish, "content_published", action_id=action_id, post_id=post.get("id"))
    log_event("content_published", action_id=action_id, post_id=post.get("id"))
    try:
        from connectors import content_sheet
        content_sheet.sync_result(row, "Published", f"Buffer receipt: {post.get('id')} ({post.get('status')})")
    except Exception as exc:
        receipt["sheet_sync_error"] = str(exc)[:300]
    return receipt


def reject(action_id: str) -> dict:
    def mutate(state):
        row = next((x for x in state.get("action_queue", []) if x.get("action_id") == action_id), None)
        if not row or row.get("type") != "CONTENT_BUFFER_POST":
            raise ValueError("Content action not found")
        if row.get("status") != "PENDING_APPROVAL":
            raise ValueError("Only pending content may be rejected")
        row["status"] = "REJECTED"
        row["rejected_at"] = _now()
        return True, dict(row)
    row = Store().transaction(mutate, "content_rejected", action_id=action_id)
    try:
        from connectors import content_sheet
        content_sheet.sync_result(row, "Rejected", f"Agent preview {action_id} rejected; nothing sent")
    except Exception:
        pass
    return row


def status_text() -> str:
    configured = bool(os.environ.get("BUFFER_API_KEY", "").strip())
    rows = [x for x in Store().rows_all().get("action_queue", []) if x.get("type") == "CONTENT_BUFFER_POST"][-5:]
    lines = ["✍️ Content Creator Agent", f"Buffer: {'configured ✅' if configured else 'not configured'}",
             "Workflow: Researcher → Critic → Creator → preview → approval → Buffer receipt"]
    lines += [f"• {x['action_id']} — {x['status']} — {x.get('platform')}" for x in reversed(rows)]
    return "\n".join(lines)


def capabilities_text() -> str:
    """Deterministic publishing capability inventory for conversational queries."""
    configured = bool(os.environ.get("BUFFER_API_KEY", "").strip())
    return "\n".join([
        "✍️ مهارات وكيل النشر الفعلية",
        "• قراءة BRAND_SETUP وPUBLISH_QUEUE من شيت المحتوى.",
        "• Researcher → Critic → Creator مع صياغة عربية/إنجليزية.",
        "• تجهيز النص، Hook، CTA، Hashtags وقراءة رابط Media_URL.",
        "• كتابة المسودة والحالة والملاحظات في صف الشيت نفسه.",
        "• دعم LinkedIn وInstagram وFacebook وX وThreads وTikTok وYouTube وPinterest وBluesky.",
        "• Preview → موافقة صريحة → Buffer → إيصال محفوظ في الشيت.",
        f"• Buffer: {'مهيأ ✅' if configured else 'غير مهيأ ❌'}.",
        "لا يدّعي النشر دون Buffer receipt فعلي.",
    ])


def publication_status_text(platform: str | None = None) -> str:
    """Report persisted publishing truth; never infer delivery from a preview."""
    rows = [x for x in Store().rows_all().get("action_queue", [])
            if x.get("type") == "CONTENT_BUFFER_POST"]
    if platform:
        rows = [x for x in rows if str(x.get("platform", "")).lower() == platform.lower()]
    executed = [x for x in rows if x.get("status") == "EXECUTED" and x.get("receipts")]
    if executed:
        row = executed[-1]
        receipt = row["receipts"][-1]
        media = "مع صورة" if row.get("image_url") else "نص فقط"
        return (f"✅ يوجد إيصال Buffer فعلي\nPlatform: {row.get('platform')}\n"
                f"Post: {receipt.get('post_id')}\nStatus: {receipt.get('status')}\nMedia: {media}")
    pending = [x for x in rows if x.get("status") == "PENDING_APPROVAL"]
    suffix = f" توجد {len(pending)} معاينة بانتظار الموافقة." if pending else " لا توجد معاينة معلقة."
    label = f" إلى {platform}" if platform else ""
    return f"❌ لا يوجد Buffer receipt يثبت إرسال محتوى{label}.{suffix}"

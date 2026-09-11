# -*- coding: utf-8 -*-
"""Gemini image/video generation -> Drive -> Sheet -> Buffer-ready URL."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from connectors import google_credentials
from engine.store import Store, log_event

API = "https://generativelanguage.googleapis.com/v1beta/interactions"
FOLDER_ID = os.environ.get("CONTENT_MEDIA_FOLDER_ID", "").strip()
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip()
VIDEO_MODEL = os.environ.get("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash").strip()
_DRIVE = None


def _key() -> str:
    value = os.environ.get("GEMINI_API_KEY", "").strip()
    if not value:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return value


def _pending(action_id: str | None) -> dict:
    rows = [x for x in Store().rows_all().get("action_queue", [])
            if x.get("type") == "CONTENT_BUFFER_POST" and x.get("status") == "PENDING_APPROVAL"]
    if action_id:
        row = next((x for x in rows if x.get("action_id") == action_id), None)
    else:
        row = rows[-1] if rows else None
    if not row:
        raise ValueError("No pending content preview found. Create one with /content_sheet Q-001")
    return row


def _prompt(row: dict, kind: str) -> str:
    plan = row.get("content_plan") or {}
    ratio = "4:5 portrait social poster" if kind == "image" else "9:16 vertical short video"
    return (
        f"Create a premium {ratio} for Life Pulse | نبض الحياة, a Saudi physical therapy and "
        "rehabilitation brand. Professional, empathetic, clinical, modern, dark navy and teal, "
        "realistic human movement, no patient identity, no diagnosis, no guaranteed outcomes. "
        f"Topic: {plan.get('goal')}. Hook: {plan.get('hook')}. Visual brief: {plan.get('image_brief')}. "
        "Keep the composition uncluttered. Do not invent statistics or medical claims. "
        "Use minimal or no rendered text because exact Arabic copy will remain in the post caption."
    )[:5000]


def _generate(row: dict, kind: str) -> tuple[bytes, str]:
    model = IMAGE_MODEL if kind == "image" else VIDEO_MODEL
    response_format = ({"type": "image", "mime_type": "image/png", "aspect_ratio": "4:5", "image_size": "2K"}
                       if kind == "image" else
                       {"type": "video", "aspect_ratio": "9:16", "resolution": "720p"})
    body = json.dumps({"model": model, "input": _prompt(row, kind),
                       "response_format": response_format}).encode("utf-8")
    req = urllib.request.Request(
        API + "?key=" + urllib.parse.quote(_key(), safe=""), data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Abdulrahman-AI-OS"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:700]
        raise RuntimeError(f"Gemini media HTTP {exc.code}: {detail}") from exc
    wanted = "image" if kind == "image" else "video"
    for step in reversed(payload.get("steps") or []):
        for item in step.get("content") or []:
            if item.get("type") == wanted and item.get("data"):
                return base64.b64decode(item["data"]), item.get("mime_type") or (
                    "image/png" if kind == "image" else "video/mp4")
    raise RuntimeError("Gemini returned no generated media")


def _drive():
    global _DRIVE
    if _DRIVE is not None:
        return _DRIVE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    _DRIVE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _DRIVE


def _upload(data: bytes, mime_type: str, name: str) -> dict:
    if not FOLDER_ID:
        raise RuntimeError("CONTENT_MEDIA_FOLDER_ID is not configured")
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    file = _drive().files().create(
        body={"name": name, "parents": [FOLDER_ID]}, media_body=media,
        fields="id,name,webViewLink", supportsAllDrives=True,
    ).execute()
    # Marketing media must be anonymously readable for Telegram and Buffer.
    _drive().permissions().create(
        fileId=file["id"], body={"type": "anyone", "role": "reader"},
        fields="id", supportsAllDrives=True,
    ).execute()
    file["directLink"] = f"https://drive.google.com/uc?export=download&id={file['id']}"
    return file


def generate(action_id: str | None, kind: str) -> dict:
    if kind not in {"image", "video"}:
        raise ValueError("Media kind must be image or video")
    row = _pending(action_id)
    data, mime = _generate(row, kind)
    ext = "png" if kind == "image" else "mp4"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    file = _upload(data, mime, f"{row['action_id']}-{stamp}.{ext}")
    url = file["directLink"]

    def save(state):
        target = next(x for x in state.get("action_queue", []) if x.get("action_id") == row["action_id"])
        if kind == "image":
            target["image_url"] = url
        else:
            target["video_url"] = url
        target["media"] = {"kind": kind, "drive_file_id": file["id"],
                           "view_url": file.get("webViewLink"), "direct_url": url}
        return True, dict(target)
    saved = Store().transaction(save, "content_media_generated", action_id=row["action_id"], kind=kind)
    try:
        from connectors import content_sheet
        queue_id = saved.get("source_queue_id")
        if queue_id:
            content_sheet.update_queue(
                str(queue_id), Media_URL=url,
                Internal_Notes=f"{kind.title()} generated: {file['id']} — review before Buffer approval",
            )
    except Exception as exc:
        file["sheet_sync_error"] = str(exc)[:300]
    log_event("content_media_generated", action_id=row["action_id"], kind=kind, file_id=file["id"])
    return {"action_id": row["action_id"], "kind": kind, "url": url,
            "view_url": file.get("webViewLink"), "file_id": file["id"],
            "sheet_sync_error": file.get("sheet_sync_error")}


def status_text() -> str:
    info = google_credentials.service_account_info() or {}
    configured = bool(os.environ.get("GEMINI_API_KEY", "").strip() and FOLDER_ID and info)
    try:
        folder = _drive().files().get(fileId=FOLDER_ID, fields="id,name,mimeType").execute() if configured else {}
        drive_state = f"connected ✅ — {folder.get('name')}" if folder else "not tested"
    except Exception as exc:
        drive_state = "failed — " + str(exc)[:180]
    return "\n".join([
        "🎨 Content Media Agent", f"Configuration: {'ready ✅' if configured else 'incomplete ❌'}",
        f"Drive: {drive_state}", f"Image model: {IMAGE_MODEL}", f"Video model: {VIDEO_MODEL}",
    ])

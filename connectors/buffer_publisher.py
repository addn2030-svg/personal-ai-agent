# -*- coding: utf-8 -*-
"""Buffer publisher — ينشر/يجدول منشورًا (نص + صورة) عبر واجهة Buffer GraphQL API.

المتطلبات:
  - مفتاح API شخصي من publish.buffer.com/settings/api
  - ضعه في متغير البيئة BUFFER_API_KEY قبل التشغيل (لا تضعه في ملفات المستودع).

ملاحظة مهمة: واجهة Buffer لا تقبل رفع الملفات مباشرة؛ يجب أن تكون الصورة
على رابط عام (raw GitHub، أو أي مستضيف صور عام) وتمرَّر عبر --image-url.

أمثلة:
  # استعراض المؤسسات والقنوات:
  BUFFER_API_KEY=xxx python3 -m connectors.buffer_publisher --list

  # إضافة منشور بصورة إلى طابور القناة:
  BUFFER_API_KEY=xxx python3 -m connectors.buffer_publisher \
      --channel-id some_channel_id \
      --text "نص المنشور" \
      --image-url https://raw.githubusercontent.com/.../assets/book-cover.jpg

  # جدولة المنشور في وقت محدد (بتوقيت السعودية افتراضيًا):
  BUFFER_API_KEY=xxx python3 -m connectors.buffer_publisher \
      --channel-id some_channel_id --text "نص" --image-url https://... \
      --due-at "2026-09-12 18:00"

  # حفظ كمسودة بدل النشر:
  ... نفس الأمر مع --draft
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.buffer.com"
DEFAULT_TZ_OFFSET = "+03:00"  # توقيت السعودية (Arabia Standard Time)

GET_ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account {
    organizations {
      id
      name
      ownerEmail
    }
  }
}
"""

GET_CHANNELS_QUERY = """
query GetChannels($organizationId: String!) {
  channels(input: { organizationId: $organizationId }) {
    id
    name
    displayName
    service
    avatar
    isQueuePaused
  }
}
"""


def _gql(query: str, variables: dict | None = None, api_key: str | None = None):
    """ينفذ طلب GraphQL واحدًا ويعيد الاستجابة كقاموس."""
    key = api_key or os.environ.get("BUFFER_API_KEY", "")
    if not key:
        raise SystemExit(
            "BUFFER_API_KEY غير مضبوط. احصل على مفتاح من "
            "publish.buffer.com/settings/api ثم: export BUFFER_API_KEY=..."
        )
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:  # خطأ HTTP (مفتاح خاطئ، صلاحيات، ...)
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"HTTP {exc.code} من Buffer: {detail}") from exc
    except URLError as exc:  # شبكة/قطع اتصال
        raise SystemExit(f"تعذر الوصول إلى {API_URL}: {exc.reason}") from exc


def _graphql_value(value) -> str:
    """يحوّل قيمة بايثون إلى نص GraphQL حرفي (escaping أساسي)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )
    return f'"{escaped}"'


def list_channels() -> None:
    data = _gql(GET_ORGANIZATIONS_QUERY)
    orgs = (data.get("data") or {}).get("account", {}).get("organizations") or []
    if not orgs:
        print("لا توجد مؤسسات مرتبطة بهذا المفتاح.")
        return
    for org in orgs:
        print(f"المؤسسة: {org.get('name')} — id: {org.get('id')}")
        channels = _gql(
            GET_CHANNELS_QUERY, {"organizationId": org["id"]}
        ).get("data", {}).get("channels") or []
        if not channels:
            print("  (لا قنوات)")
        for ch in channels:
            paused = " [متوقف]" if ch.get("isQueuePaused") else ""
            print(
                f"  - {ch.get('displayName') or ch.get('name')} "
                f"({ch.get('service')}) — channel id: {ch.get('id')}{paused}"
            )
        print()


def _normalize_due_at(raw: str, tz_offset: str) -> str:
    """يحوّل "YYYY-MM-DD HH:MM" إلى ISO-8601 بإزاحة زمنية."""
    parsed = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise SystemExit(
            f"صيغة --due-at غير مفهومة: {raw!r} — استخدم \"YYYY-MM-DD HH:MM\""
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:00") + tz_offset


def create_post(
    channel_id: str,
    text: str,
    image_url: str | None,
    due_at: str | None,
    draft: bool,
    tz_offset: str,
) -> dict:
    """يبني وينفذ mutation إنشاء المنشور."""
    if not channel_id or not text:
        raise SystemExit("--channel-id و --text مطلوبان للنشر.")

    mode = "customScheduled" if due_at else "addToQueue"
    fields = [
        f"text: {_graphql_value(text)}",
        f"channelId: {_graphql_value(channel_id)}",
        "schedulingType: automatic",
        f"mode: {mode}",
    ]
    if due_at:
        fields.append(f"dueAt: {_graphql_value(_normalize_due_at(due_at, tz_offset))}")
    if draft:
        fields.append("saveToDraft: true")
    if image_url:
        fields.append(
            "assets: [{ image: { url: "
            + _graphql_value(image_url)
            + " } }]"
        )

    mutation = (
        "mutation CreatePost {\n"
        "  createPost(input: {\n    " + ",\n    ".join(fields) + "\n  }) {\n"
        "    ... on PostActionSuccess {\n"
        "      post { id text status }\n"
        "    }\n"
        "    ... on MutationError {\n      message\n    }\n"
        "  }\n"
        "}"
    )
    data = _gql(mutation)
    payload = (data.get("data") or {}).get("createPost") or {}
    if "post" not in payload:
        errors = data.get("errors") or [payload]
        messages = "; ".join(
            e.get("message", json.dumps(e, ensure_ascii=False))
            for e in errors
            if isinstance(e, dict)
        )
        raise SystemExit(f"فشل إنشاء المنشور: {messages or data}")
    return payload["post"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m connectors.buffer_publisher",
        description="نشر/جدولة منشور في Buffer عبر واجهة GraphQL API.",
    )
    parser.add_argument("--list", action="store_true", help="استعراض المؤسسات والقنوات")
    parser.add_argument("--channel-id", help="معرّف القناة الهدف")
    parser.add_argument("--text", help="نص المنشور")
    parser.add_argument("--image-url", help="رابط عام للصورة (Buffer لا يقبل الرفع المباشر)")
    parser.add_argument("--due-at", help='وقت الجدولة: "YYYY-MM-DD HH:MM" (توقيت محلي)')
    parser.add_argument("--tz", default=DEFAULT_TZ_OFFSET,
                        help=f"إزاحة توقيت الجدولة (افتراضي {DEFAULT_TZ_OFFSET})")
    parser.add_argument("--draft", action="store_true", help="حفظ كمسودة بدل الجدولة")
    args = parser.parse_args(argv)

    if args.list:
        list_channels()
        return 0

    post = create_post(
        channel_id=args.channel_id or "",
        text=args.text or "",
        image_url=args.image_url,
        due_at=args.due_at,
        draft=args.draft,
        tz_offset=args.tz,
    )
    print(f"تم إنشاء المنشور — id: {post.get('id')} | status: {post.get('status')}")
    print(f"النص: {post.get('text', '')[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

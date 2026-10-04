# -*- coding: utf-8 -*-
"""
جسر تيليجرام — القناة الخارجية للمدير الشخصي (اختياري تمامًا).

    TELEGRAM_BOT_TOKEN=... python3 -m level2.telegram_bridge

يستمع للرسائل النصية ويرد بنفس عقل المدير (level2.agent) — نفس البروتوكولات،
نفس الحالة المحلية. لا يعتمد على أي شيء آخر: Python قياسي فقط.

ملاحظة: هذا الجسر لا يرسل أي رسالة من تلقاء نفسه — يرد فقط على من يكتب البوت،
وكل "الأثر الخارجي" في المنطق يبقى اقتراحًا (قاعدة L2).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from level2.agent import handle  # noqa: E402
from level2.state import get_store  # noqa: E402

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"
POLL_SECONDS = 30
MAX_REPLY_CHARS = 3800  # حد تيليجرام 4096 — نتجاوز أمانًا


def _call(method: str, **params) -> dict:
    body = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/{method}", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=POLL_SECONDS + 10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send(chat_id: int, text: str) -> None:
    for i in range(0, len(text), MAX_REPLY_CHARS):
        _call("sendMessage", chat_id=chat_id, text=text[i:i + MAX_REPLY_CHARS])


def main() -> None:
    if not TOKEN:
        print("⚠️  لا يوجد TELEGRAM_BOT_TOKEN — الجسر الاختياري معطّل.")
        print("    للتشغيل: TELEGRAM_BOT_TOKEN=... python3 -m level2.telegram_bridge")
        sys.exit(1)

    me = _call("getMe").get("result", {})
    print(f"🤖 جسر تيليجرام يعمل: @{me.get('username')} (Ctrl+C للإيقاف)")
    store = get_store()
    print(f"    الحالة المحلية: {store.path}")

    # قناة واحدة لكل مستخدم مصرح: نرسل الرد لمن يكتب فقط (لا بث أبدًا)
    offset = None
    while True:
        try:
            params = {"timeout": POLL_SECONDS, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            data = _call("getUpdates", **params)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = msg.get("chat", {}).get("id")
                text = (msg.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                if text.startswith("/"):
                    text = {"start": "مساعدة", "help": "مساعدة"}.get(text.split("@")[0][1:], text[1:])
                result = handle(text, channel="telegram")
                _send(chat_id, result["reply"])
        except KeyboardInterrupt:
            print("\nتم الإيقاف — حالتك محفوظة.")
            break
        except Exception as exc:  # فشل الشبكة لا يُسقط الحلقة
            print(f"[telegram] خطأ مؤقت: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()

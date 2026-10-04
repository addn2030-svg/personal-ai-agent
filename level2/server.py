# -*- coding: utf-8 -*-
"""
خادم المدير الشخصي المحلي — Python قياسي فقط (لا اعتماديات).

    python3 -m level2.server            # http://localhost:8765
    PORT=9000 python3 -m level2.server   # منفذ مخصص

الطرق:
    GET  /            واجهة الحوار الصوتي (المتصفح)
    GET  /api/brief   البريف المركز (JSON)
    GET  /api/status  حالة النظام والنموذج
    POST /api/chat    {"text": "...", "session": "..."} → رد المدير
    POST /api/energy  {"level": 4} → تسجيل طاقة
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from level2 import VERSION, llm  # noqa: E402
from level2.agent import handle  # noqa: E402
from level2.state import get_store  # noqa: E402

STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "0.0.0.0")


class Handler(BaseHTTPRequestHandler):
    server_version = f"Level2Manager/{VERSION}"

    # ── أدوات ──
    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: str, ctype: str) -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):  # سجل مختصر نظيف
        sys.stderr.write("[level2] %s %s\n" % (self.command, self.path))

    # ── GET ──
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif self.path == "/api/brief":
            self._json({"brief": get_store().brief()})
        elif self.path == "/api/status":
            self._json({
                "version": VERSION,
                "llm": llm.status(),
                "state_path": get_store().path,
                "autonomy": "L2 — تنفيذ داخلي قابل للعكس + تقرير؛ لا أثر خارجي",
            })
        elif self.path == "/api/help":
            from level2.agent import reply_help
            self._json({"help": reply_help()})
        else:
            self.send_error(404, "Not Found")

    # ── POST ──
    def do_POST(self):
        if self.path == "/api/chat":
            data = self._body()
            text = (data.get("text") or "").strip()
            if not text:
                self._json({"reply": "لم أستلم نصًا — تحدث مجددًا.", "intent": "empty"}, 400)
                return
            result = handle(text, session_id=data.get("session"), channel=data.get("channel") or "web")
            self._json(result)
        elif self.path == "/api/energy":
            data = self._body()
            try:
                level = int(data.get("level"))
                assert 1 <= level <= 10
            except (TypeError, ValueError, AssertionError):
                self._json({"error": "level يجب أن تكون 1..10"}, 400)
                return
            e = get_store().log_energy(level)
            self._json({"logged": e})
        else:
            self.send_error(404, "Not Found")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"🎙️  المدير الشخصي — Level 2 v{VERSION}")
    print(f"    الواجهة:      http://localhost:{PORT}")
    print(f"    ملف الحالة:   {get_store().path}")
    print(f"    وضع العقل:    {llm.status()['mode']}")
    print("    إيقاف: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nتم الإيقاف — حالتك محفوظة.")


if __name__ == "__main__":
    main()

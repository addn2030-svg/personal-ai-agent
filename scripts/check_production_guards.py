#!/usr/bin/env python3
"""Static guards for production transport and obvious credential leaks."""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def fail(message):
    print("❌ " + message, file=sys.stderr)
    raise SystemExit(2)


def check_transport():
    docker = (BASE / "Dockerfile").read_text(encoding="utf-8")
    start = (BASE / "scripts" / "start_production.sh").read_text(encoding="utf-8")
    webhook = (BASE / "connectors" / "telegram_webhook.py").read_text(encoding="utf-8")
    production_text = docker + "\n" + start + "\n" + webhook

    if "connectors/telegram_webhook.py" not in production_text:
        fail("production does not start telegram_webhook.py")
    if re.search(r"python\w*\s+[^\n]*telegram_bot\.py", docker + "\n" + start):
        fail("production launcher directly starts telegram_bot.py polling")
    forbidden_calls = [
        r"\bbot\.run\s*\(",
        r"api\s*\(\s*['\"]getUpdates['\"]",
        r"\.start_polling\s*\(",
    ]
    for pattern in forbidden_calls:
        if re.search(pattern, webhook):
            fail(f"production webhook contains forbidden polling call: {pattern}")
    print("✅ production transport is webhook-only")


def check_obvious_secrets():
    patterns = [
        re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
    ]
    ignored = {".git"}
    for path in BASE.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".gs", ".sh", ".bat"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            if pattern.search(text):
                fail(f"possible credential committed in {path.relative_to(BASE)}")
    print("✅ no obvious committed credentials detected")


if __name__ == "__main__":
    check_transport()
    check_obvious_secrets()

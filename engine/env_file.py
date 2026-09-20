# -*- coding: utf-8 -*-
"""Minimal, dependency-free `.env` loader.

The repo historically read configuration only from real environment variables
(Railway *Variables* in production, shell `export` locally). Several setup guides
tell you to create a `.env` file, but nothing in the code was actually reading
it. This module makes that work — with the safety rules the rest of the system
follows:

- **Real environment variables always win.** A value already present in the
  process environment is never overwritten (so a Railway variable can never be
  silently replaced by a stale file on disk).
- **No dependencies** (no `python-dotenv`) and no execution of file content:
  only `KEY=VALUE` lines are parsed.
- **Values are never logged.** `load_env()` returns *names* only, so a caller
  can safely print which variables were picked up without leaking secrets.

Supported syntax: `KEY=value`, `export KEY=value`, `#` comments, blank lines,
single/double quotes, and inline `#` comments after an unquoted value.

Usage:
    from engine.env_file import load_env
    load_env()                       # ./env at the repo root (if it exists)
    load_env("/etc/ai-os.env")       # explicit path
"""
from __future__ import annotations

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_PATH = os.path.join(BASE, ".env")


def parse_env_text(text: str) -> dict:
    """Parse `.env` content into a dict. Never raises on malformed lines."""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            # Quoted value: read up to the matching closing quote, so a trailing
            # inline comment (`KEY="value"  # note`) is dropped, not absorbed.
            quote = value[0]
            chars: list[str] = []
            escaped = False
            for char in value[1:]:
                if escaped:
                    chars.append(char)
                    escaped = False
                    continue
                if quote == '"' and char == "\\":
                    escaped = True
                    continue
                if char == quote:
                    break
                chars.append(char)
            value = "".join(chars)
        else:
            # Strip an unquoted inline comment ("# ..." preceded by whitespace).
            for marker in (" #", "\t#"):
                idx = value.find(marker)
                if idx != -1:
                    value = value[:idx]
                    break
            value = value.strip()
        out[name] = value
    return out


def load_env(path: str | None = None, override: bool = False) -> list[str]:
    """Load a `.env` file into `os.environ` and return the names that were used.

    `AI_OS_ENV_FILE` may point at a different file; an explicit `path` wins over
    both. A missing file is not an error (production uses real variables).
    Returned names are safe to print — they carry no values.
    """
    target = path or os.environ.get("AI_OS_ENV_FILE") or DEFAULT_ENV_PATH
    try:
        with open(target, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return []
    loaded: list[str] = []
    for name, value in parse_env_text(text).items():
        if not value:
            continue
        if not override and os.environ.get(name, "") != "":
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded


if __name__ == "__main__":  # pragma: no cover - manual inspection only
    names = load_env()
    print(f"env file: {os.environ.get('AI_OS_ENV_FILE') or DEFAULT_ENV_PATH}")
    print(f"variables loaded: {len(names)}")
    for name in sorted(names):
        print(f"  • {name}")  # names only — never values

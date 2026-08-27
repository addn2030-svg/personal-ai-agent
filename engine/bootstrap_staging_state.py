# -*- coding: utf-8 -*-
"""Explicit one-time bootstrap for an isolated, Telegram-disabled staging StateStore.

Production must remain fail-closed. This helper is only allowed when both:
- AI_OS_BOOTSTRAP_EMPTY_STATE=1
- AI_OS_DISABLE_TELEGRAM=1

It creates a valid empty state.json if one is missing, then validates schema while
allowing zero operational records. It never copies production state.
"""
from __future__ import annotations

import os

from engine.store import Store


def bootstrap(path: str | None = None) -> dict:
    if os.environ.get("AI_OS_BOOTSTRAP_EMPTY_STATE", "0").strip() != "1":
        raise RuntimeError("staging bootstrap is not enabled")
    if os.environ.get("AI_OS_DISABLE_TELEGRAM", "0").strip() != "1":
        raise RuntimeError("staging bootstrap requires AI_OS_DISABLE_TELEGRAM=1")

    store = Store(path) if path else Store()
    existed = os.path.exists(store.path)
    if not existed:
        store.commit(store.data, "staging_bootstrap")
    else:
        store.reload()

    store.validate(require_nonempty=False)
    return {
        "ok": True,
        "created": not existed,
        "path": store.path,
        "version": int(store.data.get("meta", {}).get("version", 0) or 0),
        "records": store.record_count(),
    }


def main():
    result = bootstrap()
    action = "created" if result["created"] else "reused"
    print(
        "✅ staging state bootstrap "
        f"{action}: version={result['version']} records={result['records']} path={result['path']}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ {exc}")
        raise SystemExit(2)

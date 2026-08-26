# -*- coding: utf-8 -*-
"""Fail closed when the operational StateStore is missing, empty, or incompatible."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "engine"))
from store import Store


def main():
    allow_empty = "--allow-empty" in sys.argv
    store = Store()
    store.validate(require_nonempty=not allow_empty)
    print(
        f"✅ state valid: schema={store.data['meta'].get('schema')} "
        f"version={store.data['meta'].get('version')} records={store.record_count()} path={store.path}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2)

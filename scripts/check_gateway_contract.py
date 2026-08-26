#!/usr/bin/env python3
"""Compare Python contract ↔ Apps Script source, and optionally ↔ live deployment."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from connectors.gateway_contract import EXPECTED_ACTIONS, ping_live

SOURCE = BASE / "connectors" / "google_sheets_webhook.gs"


def source_actions():
    text = SOURCE.read_text(encoding="utf-8")
    match = re.search(r"const\s+SUPPORTED_ACTIONS\s*=\s*\[(.*?)\];", text, re.S)
    if not match:
        raise RuntimeError("SUPPORTED_ACTIONS missing from Apps Script source")
    return frozenset(re.findall(r"['\"]([a-z_]+)['\"]", match.group(1)))


def compare(label, actual):
    if actual != EXPECTED_ACTIONS:
        missing = sorted(EXPECTED_ACTIONS - actual)
        extra = sorted(actual - EXPECTED_ACTIONS)
        raise RuntimeError(f"{label} contract drift: missing={missing} extra={extra}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="also ping deployed Apps Script")
    args = parser.parse_args()

    compare("source", source_actions())
    print("✅ source gateway actions match Python contract")
    if args.live:
        result = ping_live()
        print(f"✅ live gateway handshake: schema={result.get('schema')} actions={len(result.get('actions', []))}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(2)

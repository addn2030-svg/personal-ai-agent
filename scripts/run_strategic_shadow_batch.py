#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manual entrypoint for the explicitly approved DEV shadow batch."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from connectors import strategic_shadow_batch as batch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and write the ten fixed non-sensitive DEV shadow cases."
    )
    parser.add_argument("--confirm-run", required=True)
    parser.add_argument("--confirm-write", required=True)
    args = parser.parse_args()
    receipt = batch.run_batch(args.confirm_run, args.confirm_write)
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
    return 0 if receipt.sheet_verified and not receipt.live_effects else 1


if __name__ == "__main__":
    raise SystemExit(main())

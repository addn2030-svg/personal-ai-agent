#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${AI_OS_BOOTSTRAP_EMPTY_STATE:-0}" == "1" ]]; then
  if [[ "${AI_OS_DISABLE_TELEGRAM:-0}" != "1" ]]; then
    echo "❌ AI_OS_BOOTSTRAP_EMPTY_STATE requires AI_OS_DISABLE_TELEGRAM=1" >&2
    exit 2
  fi
  # Run as a package module so `from engine.store import Store` resolves on Railway.
  python3 -m engine.bootstrap_staging_state
  python3 engine/validate_state.py --allow-empty
else
  python3 engine/validate_state.py
fi

exec python3 -u connectors/telegram_webhook.py

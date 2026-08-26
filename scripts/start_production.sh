#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 engine/validate_state.py
exec python3 -u connectors/telegram_webhook.py

#!/usr/bin/env bash
# Abdulrahman AI OS v0.3 — دورة كاملة (سريعة + بريف + لوحة)
cd "$(dirname "$0")"
echo "=== Abdulrahman AI OS v0.3 ==="
python3 engine/import_inbox.py
python3 engine/manager.py full
if [ -f reports/dashboard-latest.html ]; then
  (xdg-open reports/dashboard-latest.html 2>/dev/null || open reports/dashboard-latest.html 2>/dev/null) &
fi

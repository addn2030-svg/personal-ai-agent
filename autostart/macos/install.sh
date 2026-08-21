#!/bin/bash
# تثبيت LaunchAgent في ماك — يعمل عند الدخول ويعيد نفسه تلقائيًا عند السقوط
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.abdulrahman.aios.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g" -e "s|__USER__|$(whoami)|g" \
    "$REPO/autostart/macos/com.abdulrahman.aios.plist.template" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "✅ LaunchAgent مُفعّل (RunAtLoad + KeepAlive)"
echo "📖 التحقق: tail -f ~/Library/Logs/aios-manager.log"
echo "⛔ الإيقاف: launchctl unload \"$PLIST\""

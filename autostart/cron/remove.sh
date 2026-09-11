#!/usr/bin/env bash
# يزيل جدولة التوقيت التلقائي (crontab + systemd timer) — بلا لمس لبقية السطور.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARK="AIOS-TIMING"

if command -v crontab >/dev/null 2>&1; then
  CURRENT="$(crontab -l 2>/dev/null || true)"
  if printf '%s\n' "$CURRENT" | grep -q "$MARK"; then
    KEPT="$(printf '%s\n' "$CURRENT" | grep -v "$MARK" || true)"
    printf '%s\n' "$KEPT" | crontab - && echo "✅ حُذفت سطور التوقيت من crontab." \
      || echo "❌ تعذّر تحديث crontab — أزل السطور الموسومة بـ $MARK يدويًا: crontab -e"
  else
    echo "ℹ️ لا سطور توقيت موسومة بـ$MARK في crontab."
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  for u in aios-timing.timer aios-timing.service; do
    if [ -f "$HOME/.config/systemd/user/$u" ]; then
      systemctl --user disable --now "$u" >/dev/null 2>&1 || true
      rm -f "$HOME/.config/systemd/user/$u"
      echo "✅ أُزيل $u"
    fi
  done
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi
echo "📖 للتحقق: crontab -l | grep $MARK · systemctl --user list-timers | grep aios"

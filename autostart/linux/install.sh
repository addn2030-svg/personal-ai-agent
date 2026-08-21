#!/bin/bash
# تثبيت خدمة systemd للمستخدم في لينكس
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p ~/.config/systemd/user
sed "s|__REPO__|$REPO|g" "$REPO/autostart/linux/aios-manager.service.template" > ~/.config/systemd/user/aios-manager.service
systemctl --user daemon-reload
systemctl --user enable --now aios-manager.service
loginctl enable-linger "$USER" 2>/dev/null || echo "ℹ️ لحالة العمل بدون جلسة مفتوحة: sudo loginctl enable-linger $USER"
echo "✅ الخدمة تعمل وستبدأ تلقائيًا مع الإقلاع"
echo "📖 التحقق: systemctl --user status aios-manager  |  journalctl --user -u aios-manager -f"

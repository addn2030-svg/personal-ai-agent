#!/usr/bin/env bash
# يركّب التوقيت التلقائي على الخادم — السطور المسؤولة عن بريف 06:30 والمسح كل 3 ساعات.
#
#   bash autostart/cron/install.sh              # crontab المستخدم (نبضة كل 5 دقائق)
#   bash autostart/cron/install.sh --native     # crontab بسطر لكل وظيفة (توقيت الخادم)
#   bash autostart/cron/install.sh --timer      # systemd user timer (بديل cron الأمتن)
#   bash autostart/cron/install.sh --print      # يطبع ما سيُركَّب فقط، بلا تعديل
#
# لماذا «نبضة» لا «06:30 sharp»؟ لأن المحرك (engine/timing.py) هو من يقرّر المستحق
# بعلامة idempotency في الحالة: نبضة فائتة أو خادم أعيد تشغيله الساعة 09:00 يولّد
# بريف اليوم فورًا مرة واحدة فقط — بينما سطر «30 6 * * *» يفوّت البريف لو كان cron
# متوقفًا تلك الدقيقة.
#
# ملاحظات للناسخ:
#   • السطور الموسومة بـ AIOS-TIMING فقط تُستبدل؛ الباقي في crontab لا يُمسّ.
#   • لا يحتاج root. لإزالته: bash autostart/cron/remove.sh
#   • الخادم بلا python3 في PATH؟ اضبط PYTHON_BIN في .env أو مرّره وقت التشغيل.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARK="AIOS-TIMING"
MODE="tick"
PRINT=0
for a in "$@"; do
  case "$a" in
    --native) MODE="native" ;;
    --timer) MODE="timer" ;;
    --print) PRINT=1 ;;
    *) echo "خيار غير معروف: $a (المتاح: --native --timer --print)" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = "timer" ]; then
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR" "$REPO/logs"
  for u in service timer; do
    sed "s|__REPO__|$REPO|g" "$REPO/autostart/cron/aios-timing.$u.template" \
      > "$UNIT_DIR/aios-timing.$u"
  done
  if [ "$PRINT" = "1" ]; then
    echo "سيُركَّب: $UNIT_DIR/aios-timing.{{service,timer}} ثم systemctl --user enable --now aios-timing.timer"
    exit 0
  fi
  systemctl --user daemon-reload
  systemctl --user enable --now aios-timing.timer
  loginctl enable-linger "$USER" 2>/dev/null || echo "ℹ️ للعمل بلا جلسة مفتوحة: sudo loginctl enable-linger $USER"
  echo "✅ مؤقّت systemd يعمل — التحقق: systemctl --user list-timers | grep aios"
  echo "📖 السجل: $REPO/logs/timing.log · الحالة: python3 engine/timing.py status"
  exit 0
fi

BLOCK="$(sed "s|__REPO__|$REPO|g" "$REPO/autostart/cron/aios-timing.crontab.template")"
if [ "$MODE" = "native" ]; then
  # يولّدها المحرك نفسه: نفس مصدر الحقيقة (مواقيت البيئة + الوسم + المسارات)
  BLOCK="$(cd "$REPO" && "${PYTHON_BIN:-python3}" engine/timing.py install-cron --mode native |
           grep -v '^# للتركيب التلقائي')"
fi
chmod +x "$REPO/scripts/aios-timing.sh"
mkdir -p "$REPO/logs"

if [ "$PRINT" = "1" ]; then
  printf '%s\n' "$BLOCK"
  exit 0
fi
if ! command -v crontab >/dev/null 2>&1; then
  echo "❌ لا يوجد أمر crontab هنا — استخدم البديل: bash autostart/cron/install.sh --timer" >&2
  exit 1
fi
CURRENT="$(crontab -l 2>/dev/null || true)"
KEPT="$(printf '%s\n' "$CURRENT" | grep -v "$MARK" || true)"
{ printf '%s\n' "$KEPT" | sed '/^[[:space:]]*$/d'; printf '%s\n' "$BLOCK"; } | crontab -
echo "✅ رُكّبت جدولة التوقيت ($MODE) في crontab المستخدم."
echo "📖 للتحقق: crontab -l | grep $MARK · python3 engine/timing.py status"
echo "📖 أول نبضة يدويًا الآن: $REPO/scripts/aios-timing.sh tick && tail -n 20 $REPO/logs/timing.log"
echo "⚠️ لا تُضِف إعادة توجيه »>> logs/timing.log 2>&1« إلى السطور — الغلاف يسجّل بنفسه."

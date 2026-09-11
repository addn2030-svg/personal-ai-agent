#!/usr/bin/env bash
# غلاف التوقيت التلقائي — السطر الذي يوضع في cron.
#
#   */5 * * * * /path/to/repo/scripts/aios-timing.sh tick
#
# لماذا غلاف ولا أمر python مباشر؟ لأنه (1) يدخل بمجلد المستودع، (2) يقرأ .env إن
# وُجد (توكن تيليجرام والمسارات على الخادم)، (3) يختار python المناسب حين لا تكون
# PATH كاملة في بيئة cron، (4) يكتب في logs/timing.log ويدوّره فلا تمتلئ القرص،
# (5) يرجع 0 عند الأعطال العابرة فلا يبعث cron سيل رسائل بريد. القفل ومنع التكرار
# يتكفّل بهما المحرك نفسه (engine/timing.py: data/.timing.lock + مفتاح الدورة).
#
# ملاحظة: الإخراج يذهب للسجل وحده؛ لا تُضِف «>> log 2>&1» في سطر cron لئلا تتكرر الأسطر.
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 2

LOG_DIR="${AIOS_TIMING_LOG_DIR:-$REPO/logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="$REPO/data"
LOG="$LOG_DIR/timing.log"

# .env اختياري — الأسرار لا تُرفع للمستودع أبدًا (انظر docs/connection-guide.md)
if [ -f "$REPO/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO/.env"
  set +a
fi

PYTHON="${PYTHON_BIN:-}"
if [ -z "$PYTHON" ]; then
  PYTHON="$(command -v python3 || command -v python || echo /usr/bin/python3)"
fi

CMD="${1:-tick}"
if [ "$#" -gt 0 ]; then shift; fi

# تدوير بسيط: فوق 2MB تذهب النسخة السابقة إلى .1
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 2097152 ]; then
  mv -f "$LOG" "$LOG.1" 2>/dev/null || true
fi

(
  echo "── $(date -u '+%Y-%m-%dT%H:%M:%SZ') aios-timing $CMD $*"
  "$PYTHON" -u engine/timing.py "$CMD" "$@" 2>&1
  RC=$?
  echo "── exited rc=$RC"
  exit "$RC"
) >>"$LOG"
RC=$?

# الفشل موثّق في logs/timing.log و data/audit.jsonl. افتراضيًا نرجع 0 حتى لا
# يبعث cron رسالة بريد كل بضع دقائق؛ AIOS_TIMING_STRICT=1 لتمرير رمز الخروج.
if [ "${AIOS_TIMING_STRICT:-0}" = "1" ]; then
  exit "$RC"
fi
exit 0

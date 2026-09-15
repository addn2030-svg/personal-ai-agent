#!/usr/bin/env bash
# التحقق الكامل من وظيفة «دفع تلقائي 375 ريال» (عتبة التفويض المالي v1.1).
# يطبع الأقسام: BUILD · MATRIX · THRESHOLD · FUNCTIONAL · MANAGER · SCHEDULER · RAG
# ويعيد 0 عند نجاح كل الأقسام، و1 عند فشل أيٍّ منها.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" -eq 0 ]; then say "✅ $2"; else say "❌ $2"; FAIL=1; fi; }

# معزل بيانات مؤقت حتى لا يمس التحقق الحالة الحقيقية
export AI_OS_DATA_DIR="$(mktemp -d)"
trap 'rm -rf "$AI_OS_DATA_DIR"' EXIT

say ""
say "=== BUILD ==="
if python3 -m compileall -q engine connectors >/dev/null 2>&1; then
  N=$(python3 - <<'PY'
import os
c=0
for d in ("engine","connectors"):
    for f in os.listdir(d):
        if f.endswith(".py"): c+=1
print(c)
PY
)
  say "build: OK ($N engines/connectors compiled)"
  chk 0 "البناء نجح"
else
  say "build: FAILED"; chk 1 "البناء فشل"
fi

say ""
say "=== MATRIX ==="
MATRIX=$(python3 engine/proactive.py matrix 2>/dev/null)
say "$MATRIX" | grep -A2 "^money" | sed 's/^/  /'
if echo "$MATRIX" | grep -q "money.*L1" && echo "$MATRIX" | grep -q "<375\|375 SAR\|→ L3"; then
  chk 0 "money L1 → upgrades to L3 if <375 SAR"
else
  chk 1 "money L1 → L3 (لم تظهر الترقية)"
fi

say ""
say "=== THRESHOLD ==="
THR=$(python3 engine/proactive.py threshold 2>/dev/null)
TEXT=$(echo "$THR" | python3 -c "import sys,json; print(json.load(sys.stdin)['threshold_text'])" 2>/dev/null)
say "  Threshold: ${TEXT:-?}"
[ "$TEXT" = "375 SAR (~100\$)" ]; chk $? "العتبة 375.0 SAR (~100\$)"

say ""
say "=== FUNCTIONAL TEST ==="
FUNC=$(python3 scripts/_money_functional.py 2>/dev/null); RC=$?
say "$FUNC" | sed 's/^/  /'
chk $RC "90 → ACT GREEN · 500 → ALERT_DRAFT RED"

say ""
say "=== MANAGER ==="
# دورة سريعة أولى (قد تكتب) ثم ثانية ← يجب «لا تغييرات» (write-on-change)
python3 engine/manager.py fast >/dev/null 2>&1
FAST2=$(python3 engine/manager.py fast 2>/dev/null | sed 's/^⚡ دورة سريعة: //')
say "  ⚡ fast: $FAST2"
if echo "$FAST2" | grep -q "لا تغييرات"; then
  chk 0 "fast: لا تغييرات (write-on-change OK)"
else
  chk 1 "fast: write-on-change"
fi

say ""
say "=== SCHEDULER ==="
DUE=$(python3 engine/scheduler.py due --date 2026-09-17 --at 07:30 2>/dev/null)
COUNT=$(echo "$DUE" | grep -oE '\([0-9]+ وظيفة' | grep -oE '[0-9]+')
JOBS=$(echo "$DUE" | grep -oE '(morning_brief|focus_block|finance_thursday)[a-z_0-9]*' | sed 's/_[0-9]*$//' | paste -sd, - | sed 's/,/ + /g')
say "  $COUNT وظائف مستحقة 07:30 ($JOBS)"
if [ "${COUNT:-0}" -eq 3 ] && echo "$JOBS" | grep -q "finance_thursday"; then
  chk 0 "3 وظائف مستحقة 07:30 (morning_brief + focus_block + finance_thursday)"
else
  chk 1 "الجدول المستحق 07:30"
fi

say ""
say "=== RAG ==="
RAGBUILD=$(python3 engine/rag.py build 2>/dev/null | tail -1)
CHUNKS=$(echo "$RAGBUILD" | grep -oE '[0-9]+ chunks' | grep -oE '[0-9]+')
HITS=$(python3 - <<'PY'
import sys; sys.path.insert(0,"engine")
import rag
res = rag.search("دفع تلقائي 375", top=8)
p = any(r["source"].startswith("prompts/") for r in res)
d = any(r["source"].startswith("docs/") for r in res)
print(f"{int(p)}{int(d)}")
PY
)
say "  ${CHUNKS:-?} chunks indexed — \"دفع تلقائي 375\" found in prompts + docs"
if [ "$HITS" = "11" ]; then
  chk 0 "RAG: العبارة موجودة في prompts وdocs"
else
  chk 1 "RAG: العبارة في prompts+docs (got $HITS)"
fi

say ""
say "=========================================="
if [ "$FAIL" -eq 0 ]; then
  say "🏁 ALL GREEN ✅ — دفع تلقائي <375 ريال يعمل، و≥375 أحمر (مسودة فقط)."
else
  say "⛔ فشل قسم أو أكثر — راجع ما فوق."
fi
exit "$FAIL"

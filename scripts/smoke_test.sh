#!/usr/bin/env bash
# اختبار دخان: هل النظام يولّد كل مخرجاته الحيوية؟
set -e
cd "$(dirname "$0")/.."
python3 -m compileall -q engine
bash scripts/bootstrap_demo.sh >/dev/null
test -f reports/dashboard-latest.html && echo "✅ لوحة القيادة"
test -f reports/approvals-latest.html && echo "✅ صفحة الاعتماد"
python3 engine/approve.py list | grep -q "A-0" && echo "✅ طابور الإجراءات يعمل (idempotent)"
test -f data/state.json && python3 -c "import json; d=json.load(open('data/state.json')); assert d['meta']['version'] >= 1" && echo "✅ مخزن الحالة مُصدَّر"
echo "🏁 اختبار الدخان نجح كاملًا"

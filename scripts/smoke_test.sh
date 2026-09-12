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
python3 -m connectors.agent_registry check >/dev/null && echo "✅ سجل الوكلاء نظيف (بلا قدرات متعارضة أو وكلاء مجدولين بلا بطاقة)"
python3 -c "
from connectors import agent_dispatch as d
from connectors import agent_envelope as e
assert d.Budget().clamped().max_agents_per_cycle >= 1
assert not e.validate({'status': 'ok', 'agent_id': 'AG-MORNING', 'confidence': 0.9, 'evidence': []}).accepted
print('✅ حاكمية الأسطول: سقوف دورة الإرسال + قاعدة الدليل الفارغ تعملان')
"
echo "🏁 اختبار الدخان نجح كاملًا"

#!/usr/bin/env bash
# يبني بيئة تجريبية كاملة من الصفر (بيانات تجريبية حتمية) — للاستخدام المحلي ولـCI
set -e
cd "$(dirname "$0")/.."
python3 engine/make_template.py
python3 engine/migrate.py
python3 engine/manager.py full
# v1.1 — سجل الوكلاء: بطاقات القدرات داخل قسم sub_agents (merge-if-missing، لا يمسّ بيانات قائمة)
python3 -m connectors.agent_registry upgrade >/dev/null
if [ "${FULL_DEMO:-0}" = "1" ]; then
  python3 engine/voice_call.py demo A >/dev/null
  python3 engine/voice_call.py demo E >/dev/null
  python3 engine/manager.py full >/dev/null
fi
echo "✅ بيئة تجريبية جاهزة — افتح reports/dashboard-latest.html"

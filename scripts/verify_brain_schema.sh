#!/usr/bin/env bash
# يتحقق أن مخطط الدماغ يفشل **ذرّيًا** حين يكون pg_trgm غير متاح.
#
# لماذا فحص مستقل:
#   لو نُفِّذ المخطط وفشل في منتصفه (وهو أشهر سيناريو عند نسيان تفعيل الامتداد)
#   لبقيت الجداول موجودة وbrain_recall مفقودة — وهي حالة أسوأ من الفشل النظيف،
#   لأن /brain_status يقول «الجداول جاهزة» ثم تفشل كل عملية استرجاع. هذا الفحص
#   يثبت أن المعاملة (begin/commit) تمنع ذلك، وأن الرسالة تشرح الحل بالعربية.
#
# يحتاج: psql + قاعدة يمكن الحذف منها (يُنشئ قاعدة منفصلة خاصة به).
set -uo pipefail

DB="brain_no_trgm_check"
SCHEMA="$(dirname "$0")/../supabase/03_brain_memory.sql"
FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" -eq 0 ]; then say "✅ $2"; else say "❌ $2"; FAIL=1; fi; }

SQL="$(cat "$SCHEMA")"

# قاعدة نظيفة بلا الامتداد
psql -q -v ON_ERROR_STOP=1 -c "drop database if exists $DB;" >/dev/null 2>&1
psql -q -v ON_ERROR_STOP=1 -c "create database $DB;" >/dev/null 2>&1 \
  || { say "❌ تعذّر إنشاء قاعدة الفحص"; exit 1; }

psql -q -d "$DB" -v ON_ERROR_STOP=1 -c "drop extension if exists pg_trgm;" >/dev/null 2>&1

# التنفيذ يجب أن يفشل
ERR="$(psql -d "$DB" -v ON_ERROR_STOP=1 -f "$SCHEMA" 2>&1 >/dev/null)"
STATUS=$?
chk $([ "$STATUS" -ne 0 ] && echo 0 || echo 1) "المخطط يفشل على قاعدة بلا pg_trgm"

if printf '%s' "$ERR" | grep -q "pg_trgm"; then
  chk 0 "الرسالة تذكر الامتداد المفقود"
else
  chk 1 "الرسالة لا تذكر pg_trgm"; printf '%s\n' "$ERR" | tail -5 | sed 's/^/   /'
fi

if printf '%s' "$ERR" | grep -qi "Extensions"; then
  chk 0 "الرسالة تشرح مكان التفعيل (Database → Extensions)"
else
  chk 1 "الرسالة لا تشرح مكان التفعيل"
fi

# لا كائنات متبقية: هذا هو جوهر الفحص
COUNT="$(psql -tA -d "$DB" -c "
  select count(*) from pg_tables where schemaname='public' and tablename like 'brain%';")"
FUNCS="$(psql -tA -d "$DB" -c "
  select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  where n.nspname='public' and proname like 'brain%';")"
chk $([ "$COUNT" = "0" ] && echo 0 || echo 1) "لا جداول متبقية (المطلوب 0، الموجود $COUNT)"
chk $([ "$FUNCS" = "0" ] && echo 0 || echo 1) "لا دوال متبقية (المطلوب 0، الموجود $FUNCS)"

psql -q -c "drop database if exists $DB;" >/dev/null 2>&1

say ""
if [ "$FAIL" -eq 0 ]; then
  say "🏁 الفشل ذرّي وموجّه — لا مخطط نصف مبني."
else
  say "🛑 فشل فحص الذرّية."
fi
exit "$FAIL"

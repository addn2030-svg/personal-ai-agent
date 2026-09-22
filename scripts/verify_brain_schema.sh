#!/usr/bin/env bash
# يتحقق أن مخطط الدماغ يفشل **ذرّيًا**: لا «مخطط نصف مبني».
#
# لماذا هذا الفحص مهم:
#   لو نُفِّذ المخطط وفشل في منتصفه لبقيت الجداول موجودة وbrain_recall مفقودة —
#   وهي حالة أسوأ من الفشل النظيف، لأن /brain_status يقول «الجداول جاهزة» ثم
#   تفشل كل عملية استرجاع. المعاملة (begin/commit) تمنع ذلك، وهذا الفحص يثبته.
#
# كيف نُجبر الفشل في منتصف السكربت (درس من محاولة سابقة):
#   `drop extension pg_trgm` لا يُنشئ الحالة المطلوبة على PostgreSQL حديث، لأن
#   الامتداد يبقى **متاحًا** فيُثبّته السكربت بنجاح (pg_trgm امتداد موثوق يمكن
#   لمالك قاعدة البيانات تفعيله). والمحاولة الأولى سقطت في هذا الفخ تحديدًا.
#   الحالة الحقيقية التي نريد اختبارها هي: **فشل تنفيذي في منتصف السكربت**.
#   نُنتجها بدور يملك CREATE على المخطط (فتنجح الجداول) ولا يملك CREATE على
#   قاعدة البيانات (فيفشل `create extension`) — أي فشل بعد إنشاء كائنات، وهو
#   بالضبط ما يجب أن تتراجع عنه المعاملة.
#
# ملاحظة: حالة «الامتداد غير متاح أصلًا» (نسخة PostgreSQL بلا pg_trgm) تحققت
# يدويًا على نسخة لا تحمل الامتداد: الفشل كان ذرّيًا كذلك مع رسالة عربية تشرح
# مكان التفعيل.
#
# يحتاج: صلاحية إنشاء دور وقاعدة (postgres). لا يمس أي قاعدة قائمة.
set -uo pipefail

DB="brain_guard_check"
ROLE="brain_limited"
SCHEMA="$(dirname "$0")/../supabase/03_brain_memory.sql"
FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" -eq 0 ]; then say "✅ $2"; else say "❌ $2"; FAIL=1; fi; }
psql_admin() { psql -v ON_ERROR_STOP=1 "$@"; }

# ------------------------------------------------------------------ التهيئة
psql_admin -q -c "drop database if exists $DB;" >/dev/null 2>&1
psql_admin -q -c "drop role if exists $ROLE;" >/dev/null 2>&1
# تخطّي صريح عند تعذّر التهيئة. و«التخطّي» في CI يُفشل الفحص (BRAIN_GUARD_STRICT=1)
# لأن فحصًا لا يُنفَّذ ثم يُعدّ ناجحًا هو بالضبط ما نحمي أنفسنا منه.
skip() {
  if [ "${BRAIN_GUARD_STRICT:-0}" = "1" ]; then
    say "::error::تعذّر إجبار الفشل في هذه البيئة — الفحص لم يُنفَّذ (ولا يُعدّ نجاحًا): $1"
    exit 1
  fi
  say "::warning::تخطّي فحص الذرّية: $1"
  exit 0
}

psql_admin -q -c "drop database if exists $DB;" >/dev/null 2>&1
psql_admin -q -c "drop role if exists $ROLE;" >/dev/null 2>&1
psql_admin -q -c "create role $ROLE login nosuperuser nocreatedb password 'limited_only';" >/dev/null 2>&1 \
  || skip "تعذّر إنشاء الدور (يحتاج صلاحية إنشاء دور)"
psql_admin -q -c "create database $DB;" >/dev/null 2>&1 \
  || { say "❌ تعذّر إنشاء قاعدة الفحص"; exit 1; }

# الدور: يكتب الجداول (CREATE على المخطط) لكنه لا يستطيع تفعيل الامتداد.
# ⚠️ لا نمنح CREATE على قاعدة البيانات عن قصد: pg_trgm امتداد **موثوق**، ومنح
# CREATE على القاعدة يكفي لتفعيله — وهذا ما جعل المحاولة السابقة «تنجح» في CI
# ثم يُرفض الفحص (بشكل صحيح) لأنه لم يُجرَّب شيء. المطلوب هو الاتصال والإنشاء
# في المخطط فقط.
psql_admin -q -d "$DB" -c "grant usage, create on schema public to $ROLE;" >/dev/null 2>&1
psql_admin -q -d "$DB" -c "grant connect, temporary on database $DB to $ROLE;" >/dev/null 2>&1

# ------------------------------------------------------------------ التنفيذ
ERR="$(PGUSER="$ROLE" PGPASSWORD=limited_only psql -h "${PGHOST:-localhost}" -d "$DB" \
        -v ON_ERROR_STOP=1 -f "$SCHEMA" 2>&1 >/dev/null)"
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
  psql_admin -q -c "drop database if exists $DB;" >/dev/null 2>&1
  psql_admin -q -c "drop role if exists $ROLE;" >/dev/null 2>&1
  skip "المخطط اكتمل مع أن الامتداد كان يجب أن يفشل (المصادقة أو الصلاحيات مختلفة)"
fi
chk 0 "المخطط يفشل عندما يتعذّر تفعيل الامتداد"

if printf '%s' "$ERR" | grep -q "pg_trgm"; then
  chk 0 "الرسالة تذكر pg_trgm (يعرف المستخدم أين المشكلة)"
else
  chk 1 "الرسالة لا تذكر pg_trgm"; printf '%s\n' "$ERR" | tail -5 | sed 's/^/   /'
fi

# --------------------------------------------------------------- التراجع؟
COUNT="$(psql_admin -tA -d "$DB" -c "
  select count(*) from pg_tables where schemaname='public' and tablename like 'brain%';")"
FUNCS="$(psql_admin -tA -d "$DB" -c "
  select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  where n.nspname='public' and proname like 'brain%';")"
chk $([ "$COUNT" = "0" ] && echo 0 || echo 1) "لا جداول متبقية (المطلوب 0، الموجود $COUNT)"
chk $([ "$FUNCS" = "0" ] && echo 0 || echo 1) "لا دوال متبقية (المطلوب 0، الموجود $FUNCS)"

# ------------------------------------------------------------------ التنظيف
psql_admin -q -c "drop database if exists $DB;" >/dev/null 2>&1
psql_admin -q -c "drop role if exists $ROLE;" >/dev/null 2>&1

say ""
if [ "$FAIL" -eq 0 ]; then
  say "🏁 الفشل ذرّي: لا مخطط نصف مبني."
else
  say "🛑 فشل فحص الذرّية."
fi
exit "$FAIL"

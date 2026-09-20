#!/usr/bin/env bash
# التحقق الكامل من طبقة Supabase: نسخ الحالة خارج الخادم + مرآة المهام.
# الأقسام: BUILD · CONFIG · SQL · MIRROR · UNIT · E2E · BOT · SETUP
# يعيد 0 عند نجاح كل الأقسام، و1 عند فشل أيٍّ منها.
# لا يتصل بأي مشروع Supabase حقيقي ولا يحتاج أي مفتاح.
set -uo pipefail
cd "$(dirname "$0")/.."

FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" -eq 0 ]; then say "✅ $2"; else say "❌ $2"; FAIL=1; fi; }

# عزل بيانات مؤقت حتى لا يمس التحقق الحالة الحقيقية
export AI_OS_DATA_DIR="$(mktemp -d)"
export PYTHONPATH="engine:connectors:${PYTHONPATH:-}"
trap 'rm -rf "$AI_OS_DATA_DIR"' EXIT

run_tests() {  # run_tests <module> <label>
  local out status count
  out=$(python3 -m unittest "$1" 2>&1)
  status=$?
  count=$(printf '%s\n' "$out" | grep -oE 'Ran [0-9]+ tests?' | tail -1)
  if [ "$status" -eq 0 ]; then
    chk 0 "$2 ($count)"
  else
    chk 1 "$2"
    printf '%s\n' "$out" | tail -25 | sed 's/^/  /'
  fi
}

say ""
say "=== BUILD ==="
python3 -m compileall -q engine connectors >/dev/null 2>&1
chk $? "engine/ + connectors/ تُبنى بلا أخطاء"

say ""
say "=== CONFIG ==="
OUT=$(python3 -m connectors.supabase_client 2>&1)
STATUS=$?
if echo "$OUT" | grep -q "Supabase"; then
  chk 0 "فحص الإعداد يعمل (exit=$STATUS — 2 يعني غير مضبوط، وهذا متوقع هنا)"
else
  chk 1 "فحص الإعداد لم يُنتج مخرجات مفهومة"
fi
say "$OUT" | sed 's/^/  /'

if python3 - <<'PYEOF'
import sys
sys.path.insert(0, "connectors")
from supabase_client import load_config

env = {"SUPABASE_URL": "https://demo1234.supabase.co", "SUPABASE_ANON_KEY": "sb_publishable_demo_key"}
assert load_config(lambda n: env.get(n, "")).configured, "الإعداد القانوني لم يُقبل"
assert not load_config(lambda n: env.get(n, "")).can_write, "المفتاح العام مُنح صلاحية كتابة"
env["SUPABASE_WRITE_ENABLED"] = "1"
assert not load_config(lambda n: env.get(n, "")).can_write, "الكتابة فُتحت بمفتاح عام"
env["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_demo_key"
assert load_config(lambda n: env.get(n, "")).can_write, "المفتاح السري + العلم لم يفتح الكتابة"
raise SystemExit(0)
PYEOF
then chk 0 "حواجز المفاتيح سليمة (عام = قراءة فقط · سري + علم = كتابة)"; else chk 1 "حواجز المفاتيح"; fi

say ""
say "=== SQL ==="
SQL=$(python3 -m connectors.supabase_client --sql all 2>&1)
echo "$SQL" | grep -q "create table if not exists public.state_snapshots" \
  && chk 0 "SQL النسخ الاحتياطي (01) متاح" || chk 1 "SQL النسخ الاحتياطي مفقود"
echo "$SQL" | grep -q "create table if not exists public.tasks_mirror" \
  && chk 0 "SQL مرآة المهام (02) متاح" || chk 1 "SQL مرآة المهام مفقود"
[ "$(echo "$SQL" | grep -ci "enable row level security")" -ge 2 ] \
  && chk 0 "RLS مفعّل في الجدولين" || chk 1 "RLS غير مفعّل في أحد الجدولين"
if python3 - <<'PYEOF'
import sys
sys.path.insert(0, "connectors")
from supabase_client import read_sql

head = read_sql("02_tasks_mirror.sql").split("-- 6)")[0]
active = [line for line in head.splitlines() if line.strip().lower().startswith("create policy")]
assert not active, f"سياسة فعّالة غير متوقعة: {active}"
assert "revoke all" in head.lower(), "لا يوجد revoke للمفتاح العام"
assert "security_invoker" in head.lower(), "عرض القراءة غير محمي من انتحال الصلاحيات"
raise SystemExit(0)
PYEOF
then chk 0 "لا سياسات متساهلة على المرآة + المفتاح العام محجوب (revoke)"; else chk 1 "فحص سياسات المرآة"; fi

say ""
say "=== MIRROR ==="
STATS=$(python3 -m connectors.supabase_tasks stats 2>&1)
if echo "$STATS" | grep -q "المهام"; then
  chk 0 "إحصاء المهام المحلي يعمل بلا Supabase"
  echo "$STATS" | head -3 | sed 's/^/  /'
else
  chk 1 "إحصاء المهام"; echo "$STATS" | sed 's/^/  /'
fi

if python3 - <<'PYEOF'
import datetime as dt
import os
import sys
sys.path.insert(0, "connectors")
import supabase_tasks as t

state = {"meta": {"version": 3}, "tasks": [
    {"العنوان": "متأخرة", "الأولوية": "عالية", "الحالة": "لم تبدأ",
     "الموعد النهائي": "2020-01-01", "المصدر": "صندوق الصوت"},
    {"العنوان": "منجزة", "الحالة": "منجزة", "الموعد النهائي": "2020-01-01"},
]}
today = dt.date(2026, 9, 20)
rows = t.task_rows(state, today=today)
assert len(rows) == 2, rows
by_title = {row["title"]: row for row in rows}
assert by_title["متأخرة"]["is_overdue"] and by_title["متأخرة"]["status_norm"] == "not_started"
assert not by_title["منجزة"]["is_open"]
# المعرّف حتمي: نفس المهمة ⇒ نفس الصف (وإلا لصار كل sync تكرارًا)
again = t.task_rows(state, today=today)
assert [r["id"] for r in again] == [r["id"] for r in rows], "المعرّف غير حتمي"
assert t.normalize_status("قيد التنفيذ") == "in_progress"
assert t.normalize_status("in_progress") == "in_progress"
assert t.normalize_status("شيء غريب") == "unknown", "لا نخمّن الحالة المجهولة"
# الكتابة/الجدولة مغلقة افتراضيًا حتى مع مفتاح سري
os.environ["SUPABASE_URL"] = "https://demo.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_demo_key"
assert not t.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}), "الجدولة يجب أن تكون مغلقة افتراضيًا"
raise SystemExit(0)
PYEOF
then chk 0 "تعيين الحقول · توحيد الحالات · المعرّف الحتمي · الجدولة المغلقة"; else chk 1 "منطق المرآة"; fi

say ""
say "=== PERSISTENCE (مضيف بلا قرص) ==="
if python3 - <<'PYEOF'
import os
import sys
sys.path.insert(0, ".")
from connectors import state_persistence
from connectors.supabase_client import truthy

# حواجز: لا شيء تلقائي بلا راية صريحة
for flag in ("AI_OS_STATE_PERSIST", "AI_OS_STATE_RESTORE_ON_BOOT"):
    assert not state_persistence.enabled(flag), f"{flag} يجب أن يكون مطفأً افتراضيًا"
# قراءة الرايات متسامحة مع حالة الأحرف (فقدان صامت أسوأ من رفض)
for value in ("1", "true", "TRUE", "Yes", "ON"):
    assert truthy(value), value
for value in ("", "0", "false", "off", "random"):
    assert not truthy(value), value
# الحالة مستوردة بلا شبكة
assert callable(state_persistence.restore_on_boot)
assert callable(state_persistence.push_if_changed)
# الإقلاع المتدرّج: لا سقوط عند غياب الإعداد، والرابط العام يُكتشف من المنصة
from connectors.telegram_webhook import _resolve_public_base_url
assert _resolve_public_base_url({"RENDER_EXTERNAL_HOSTNAME": "x.onrender.com"}) \
    == "https://x.onrender.com"
assert _resolve_public_base_url({"RAILWAY_PUBLIC_DOMAIN": "y.up.railway.app"}) \
    == "https://y.up.railway.app"
raise SystemExit(0)
PYEOF
then chk 0 "استمرارية الحالة مطفأة افتراضيًا + قراءة رايات متسامحة"; else chk 1 "حواجز الاستمرارية"; fi

say ""
say "=== ROLLOUT ==="
PHASE=$(python3 -m engine.rollout status 2>&1 || true)
if printf '%s' "$PHASE" | grep -q "خاملة"; then
  chk 0 "المرحلة الافتراضية خاملة (لا أتمتة بلا قرار)"
else
  chk 1 "المرحلة الافتراضية ليست dormant"; printf '%s\n' "$PHASE" | sed 's/^/  /'
fi
if python3 - <<'PYEOF'
import datetime as dt
import os
import sys
sys.path.insert(0, ".")
from engine import rollout
from connectors import supabase_tasks

# لا مرحلة تُطفئ شيئًا من سير العمل القديم
for phase in rollout.PHASES:
    assert rollout.capabilities(phase)["automation_write"] in (True, False)
assert rollout.current_phase() == "dormant"

# الأتمتة تحتاج المرحلة **والراية** معًا
os.environ["SUPABASE_URL"] = "https://demo.supabase.co"
os.environ["SUPABASE_BACKUP_SCHEDULE_ENABLED"] = "1"
now = dt.datetime(2026, 9, 20, 9, 0)
assert not supabase_tasks.daily_due(now, {}), "الأتمتة اشتغلت في dormant — خلل"
rollout.set_phase("shadow")
rollout.set_phase("canary")
assert not supabase_tasks.daily_due(now, {}), "الأتمتة اشتغلت في canary — خلل"
rollout.set_phase("dual")
assert supabase_tasks.daily_due(now, {}), "الأتمتة لم تشتغل في dual"

# التراجع فوري وبلا شروط، ولا يمحو شيئًا
rollout.kill(reason="فحص")
assert rollout.current_phase() == "dormant"
assert not supabase_tasks.daily_due(now, {}), "التراجع لم يوقف الأتمتة"

# القفز ممنوع، والمرحلة الأخيرة لا تُفرض
try:
    rollout.set_phase("primary")
    raise AssertionError("القفز إلى primary نجح — يجب أن يُرفض")
except ValueError:
    pass
raise SystemExit(0)
PYEOF
then chk 0 "المراحل · الصمام المزدوج · التراجع الفوري · منع القفز"; else chk 1 "منطق المراحل"; fi

say ""
say "=== UNIT ==="
run_tests tests.test_supabase "اختبارات الوحدة (مفاتيح · حواجز · بصمة · استعادة · .env)"
run_tests tests.test_supabase_tasks "اختبارات مرآة المهام (تعيين · إحصاء · مزامنة · جدولة · pull)"
run_tests tests.test_rollout "اختبارات التشغيل التدريجي (مراحل · بوابة · تراجع · توازٍ)"
run_tests tests.test_state_persistence "اختبارات استمرارية الحالة (إقلاع · دفع تفاضلي · إشارات)"
run_tests tests.test_webhook_boot "اختبارات إقلاع الخدمة (فشل مُعلَن لا حلقة إعادة تشغيل)"

say ""
say "=== E2E ==="
run_tests tests.test_supabase_e2e "دورة كاملة + ترقية تدريجية على خادم محلي (16 سيناريو)"

say ""
say "=== BOT ==="
BOT=$(python3 - <<'PYEOF' 2>&1
import sys
sys.path.insert(0, "engine")
import telegram_bot as tb
assert "Supabase" in tb.supabase_text()
assert "Supabase" in tb.supabase_text("list")
stats = tb.tasks_stats_text()
assert "المهام" in stats, stats
assert "خاملة" in tb.rollout_text(), "أمر المرحلة لا يعمل"
assert "أُوقف" in tb.rollout_text(kill=True), "مفتاح الإيقاف لا يعمل"
print(stats.splitlines()[0])
PYEOF
)
if [ $? -eq 0 ]; then
  chk 0 "أوامر تيليجرام تعمل بلا إعداد (/backup_now · /backups · /tasks_stats · /rollout): $BOT"
else
  chk 1 "أوامر تيليجرام: $BOT"
fi

say ""
say "=== DEPLOY (استضافة بلا قرص) ==="
if [ -f render.yaml ] && [ -f docs/free-hosting-migration.md ]; then
  chk 0 "ملفا النشر موجودان (render.yaml + دليل الانتقال)"
else
  chk 1 "ملفا النشر" "render.yaml أو docs/free-hosting-migration.md غير موجود"
fi
run_tests tests.test_render_deploy "اختبارات ملف النشر (بنية · أسرار · استمرارية · فحص ذاتي)"

say ""
say "=== CONNECTION SETUP ==="
# ملاحظة: connection_setup يعيد 2 عندما تكون قناة مطلوبة ناقصة (وهو متوقع في هذا
# التحقق المعزول)، لذا نلتقط المخرجات أولًا بدل تمريرها في أنبوب مع pipefail.
SETUP=$(python3 -m connectors.connection_setup 2>&1 || true)
if printf '%s\n' "$SETUP" | grep -q "Supabase"; then
  chk 0 "Supabase مسجّل في فحص القنوات الشامل (/diag و --guide supabase)"
else
  chk 1 "Supabase غير مسجّل في connection_setup"
fi
GUIDE=$(python3 -m connectors.connection_setup --guide supabase 2>&1 || true)
if printf '%s' "$GUIDE" | grep -q "API Keys"; then
  chk 0 "الدليل --guide supabase يعرض الواجهة الحالية (Settings → API Keys)"
else
  chk 1 "دليل supabase لا يذكر الواجهة الحالية"
fi

say ""
if [ "$FAIL" -eq 0 ]; then
  say "🏁 كل فحوص Supabase نجحت."
  say "   للفحص الحي على مشروعك الحقيقي: python3 -m connectors.supabase_client --live"
else
  say "🛑 فشل فحص واحد أو أكثر — راجع السطور أعلاه."
fi
exit "$FAIL"

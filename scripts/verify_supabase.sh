#!/usr/bin/env bash
# التحقق الكامل من موصل Supabase (نسخ الحالة خارج الخادم).
# الأقسام: BUILD · CONFIG · SQL · UNIT · E2E · BOT
# يعيد 0 عند نجاح كل الأقسام، و1 عند فشل أيٍّ منها.
# لا يتصل بأي مشروع Supabase حقيقي ولا يحتاج أي مفتاح.
set -uo pipefail
cd "$(dirname "$0")/.."

FAIL=0
say() { printf '%s\n' "$*"; }
chk() { if [ "$1" -eq 0 ]; then say "✅ $2"; else say "❌ $2"; FAIL=1; fi; }

# عزل بيانات مؤقت حتى لا يمس التحقق الحالة الحقيقية
export AI_OS_DATA_DIR="$(mktemp -d)"
export PYTHONPATH="engine:${PYTHONPATH:-}"
trap 'rm -rf "$AI_OS_DATA_DIR"' EXIT

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

if python3 - <<'PY'
import sys
sys.path.insert(0, "connectors")
from supabase_client import load_config
env = {"SUPABASE_URL": "https://demo1234.supabase.co", "SUPABASE_ANON_KEY": "sb_publishable_demo_key"}
cfg = load_config(lambda n: env.get(n, ""))
assert cfg.configured, "الإعداد القانوني لم يُقبل"
assert not cfg.can_write, "المفتاح العام مُنح صلاحية كتابة — خلل أمني"
env["SUPABASE_WRITE_ENABLED"] = "1"
assert not load_config(lambda n: env.get(n, "")).can_write, "الكتابة فُتحت بمفتاح عام — خلل أمني"
env["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_demo_key"
assert load_config(lambda n: env.get(n, "")).can_write, "المفتاح السري + العلم لم يفتح الكتابة"
raise SystemExit(0)
PY
then chk 0 "حواجز المفاتيح سليمة (عام = قراءة فقط · سري + علم = كتابة)"; else chk 1 "حواجز المفاتيح"; fi

say ""
say "=== SQL ==="
SQL=$(python3 -m connectors.supabase_client --sql 2>&1)
echo "$SQL" | grep -q "create table if not exists public.state_snapshots" \
  && chk 0 "SQL الإعداد متاح عبر --sql" || chk 1 "SQL الإعداد مفقود"
echo "$SQL" | grep -qi "enable row level security" \
  && chk 0 "RLS مفعّل في المخطط" || chk 1 "RLS غير مفعّل"

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
say "=== UNIT ==="
run_tests tests.test_supabase "اختبارات الوحدة نجحت (مفاتيح · حواجز · بصمة · استعادة · .env)"

say ""
say "=== E2E ==="
run_tests tests.test_supabase_e2e "دورة كاملة على خادم PostgREST محلي (دفع → عرض → استعادة)"

say ""
say "=== BOT ==="
BOT=$(python3 - <<'PY' 2>&1
import sys
sys.path.insert(0, "engine")
import telegram_bot as tb
text = tb.supabase_text()
assert "Supabase" in text, text
text = tb.supabase_text("list")
assert "Supabase" in text, text
print(text.splitlines()[0])
PY
)
if [ $? -eq 0 ]; then chk 0 "أوامر تيليجرام تتدهور بلطف بلا إعداد: $BOT"; else chk 1 "أمر تيليجرام: $BOT"; fi

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

# ☁️ إعداد Supabase — نسخ الحالة خارج الخادم

موصل Supabase يضيف **طبقة متانة** للنظام: الحالة (`data/state.json`) تُنسخ كاملةً،
موقّعة ببصمة sha256، إلى جدول في Supabase. لماذا؟

| المخاطرة | قبل | بعد |
|---|---|---|
| حذف خدمة Railway أو فقدان الـVolume | تذهب الحالة والأرشيف | نسخة كاملة خارج الخادم تُستعاد في دقيقة |
| النسخ الدوارة (`data/backups/`) | على **نفس** القرص | نسخة مستقلة في مشروع آخر |
| خطأ بشري يفسد الحالة | لا مرجع خارجي | مرجع موقّع يمكن مقارنته |

الخطر المتبقي موثَّق في `docs/agent3-p0-adjudication.md` (بند «Postgres deferred»).
هذا الموصل يغلق *فقدان البيانات* دون نقل مصدر الحقيقة: **`state.json` يبقى المرجع**،
وSupabase نسخة احتياطية لا أكثر.

---

## ⚠️ قواعد الأمان (اقرأها أولًا)

1. **لا تُلصق أي مفتاح في محادثة** — لا هنا، ولا في تيليجرام، ولا في أي «طلب إعداد».
   المفاتيح تُوضع في ملف `.env` محليًا أو في Railway → Variables.
2. **المفتاح السري (`secret` / `service_role`) يبقى على الخادم.** هذا المفتاح يتجاوز
   RLS ويقرأ ويكتب كل صف. لا يدخل أي واجهة متصفح، ولا GitHub، ولا رسالة.
3. **المفتاح العام (`publishable` / `anon`) للقراءة فقط.** حتى لو نُشر فلا يقرأ شيئًا
   من جدول النسخ، لأن الجدول بلا سياسات RLS (مسدود على العام).
4. **الكتابة مغلقة افتراضيًا.** لا يكتب الموصل إلا إذا اجتمع: مفتاح سري **و**
   `SUPABASE_WRITE_ENABLED=1`.
5. **الاستعادة من الطرفية فقط** — لا أمر تيليجرام يكتب على `state.json`. الاستعادة
   تكتب الملف الحقيقي، فتبقى قرارًا واعيًا أمام شاشة كاملة (مع نسخة محلية قبلها).

---

## 1️⃣ الحصول على القيم — الواجهة الحالية

> ملاحظة: الخطوات القديمة تقول **Settings → API**. هذه الصفحة لم تعد موجودة بهذا الاسم؛
> صارت **Settings → API Keys**، وأصبح زر **Connect** يظهر الرابط والمفتاح مباشرةً.

**الطريق الأسرع:** افتح `supabase.com/dashboard` → اختر المشروع → زر **Connect** →
تجد **Project URL** و**Publishable key** جاهزين للنسخ.

**الطريق الكامل:** المشروع → **Settings** (⚙️ في الشريط الجانبي) → **API Keys**.

| ما تراه في اللوحة | ماذا يعني | اسم المتغير عندنا |
|---|---|---|
| **Project URL** — `https://abcdefgh.supabase.co` | عنوان المشروع | `SUPABASE_URL` |
| **Publishable key** — `sb_publishable_…` | قراءة فقط عبر RLS | `SUPABASE_ANON_KEY` |
| **Secret key** — `sb_secret_…` | يقرأ ويكتب كل شيء (خادم فقط) | `SUPABASE_SERVICE_ROLE_KEY` |
| **Project API keys → anon (public)** — JWT يبدأ بـ`eyJ…` | الاسم القديم للمفتاح العام | `SUPABASE_ANON_KEY` |
| **Project API keys → service_role** — JWT يبدأ بـ`eyJ…` | الاسم القديم للسري | `SUPABASE_SERVICE_ROLE_KEY` |

النظامان يعملان بالتوازي؛ مفاتيح `anon`/`service_role` تُهمَل نهاية 2026، والموصل
يفهم الاثنين ويكتشف نوع المفتاح تلقائيًا.

❗️ لا تنسخ رابط اللوحة (`supabase.com/dashboard/...`) — الموصل يرفضه برسالة واضحة،
والصحيح هو `https://<ref>.supabase.co`.

---

## 2️⃣ ضبط المتغيرات

### محليًا — ملف `.env` في جذر المستودع

```bash
cd /path/to/personal-ai-agent
cp .env.example .env      # ثم افتح .env واملأ القيم
python3 -m connectors.connection_setup    # يتأكد أن الملف صار مقروءًا فعلًا
```

`.env` و`.env.*` مستثناة في `.gitignore` — لا تُرفع أبدًا.
(المتغيرات الحقيقية في البيئة تتقدّم دائمًا على الملف، فلا يستطيع ملف قديم أن يطغى
على إعداد Railway.)

### على Railway — Variables

| المتغير | القيمة |
|---|---|
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | المفتاح السري (خادم فقط) |
| `SUPABASE_WRITE_ENABLED` | `1` لتفعيل الدفع |

اختياري: `SUPABASE_ANON_KEY` (للقراءة العامة)، `SUPABASE_STATE_TABLE` (اسم الجدول،
افتراضيًا `state_snapshots`)، `SUPABASE_SCHEMA`، `SUPABASE_TIMEOUT_SECONDS`.

---

## 3️⃣ إنشاء الجدول — مرة واحدة

انسخ SQL واعرضه من الموصل نفسه:

```bash
python3 -m connectors.supabase_client --sql
```

ثم في Supabase: **SQL Editor** → **New query** → الصق → **Run**.

النتيجة جدول واحد + RLS مفعّل **وبلا أي سياسة** = لا أحد بالمفتاح العام يقرأ أو يكتب،
فقط المفتاح السري من الخادم.

| العمود | المعنى |
|---|---|
| `id` | رقم النسخة (تستخدمه في الاستعادة) |
| `created_at` | وقت الدفع (UTC) |
| `schema` / `state_version` | من `meta` داخل الحالة |
| `reason` | سبب النسخة (`manual` · `أمر تيليجرام` · أي نص) |
| `sha256` | بصمة التمثيل القانوني — تُفحص قبل أي استعادة |
| `byte_size` | حجم `state.json` وقت النسخ |
| `payload` | **الحالة كاملة** بصيغة jsonb |

> لماذا بصمة «قانونية»؟ عمود `jsonb` لا يحفظ ترتيب المفاتيح ولا التنسيق، فالبصمة
> تُحسب على تمثيل مرتَّب (`sort_keys`) حتى تنجو من رحلة الذهاب والعودة — ولو حُسبت على
> بايتات الملف الخام لبدت **كل** استعادة «تالفة».

---

## 4️⃣ التحقق

```bash
python3 -m connectors.supabase_client --check    # الإعداد ورتبة المفتاح (بلا شبكة)
python3 -m connectors.supabase_client --live     # اتصال حقيقي + عدد النسخ المرئية
python3 -m connectors.connection_setup --live    # الفحص الشامل لكل القنوات
python3 engine/backup_verify.py                  # سلامة الحالة والنسخ المحلية
```

من تيليجرام: `/diag` يعرض سطر `Supabase: ok/optional/…`، ثم `/backup_now`.

---

## 5️⃣ الاستخدام اليومي

```bash
# نسخة الآن
python3 -m connectors.supabase_state push --reason "قبل ترحيل Railway"

# آخر النسخ
python3 -m connectors.supabase_state list --limit 10

# فحص نسخة (بصمة + الأقسام) بلا أي كتابة
python3 -m connectors.supabase_state show --id 12

# معاينة الاستعادة — لا تلمس القرص
python3 -m connectors.supabase_state restore --id 12

# الاستعادة الفعلية (تأخذ نسخة محلية أولًا ثم تكتب ذرّيًا)
python3 -m connectors.supabase_state restore --id 12 --apply

# تقليم: الاحتفاظ بأحدث 30 نسخة
python3 -m connectors.supabase_state prune --keep 30
```

من تيليجرام: `/backup_now` نسخة فورية · `/backups` آخر النسخ.
(لا يوجد أمر استعادة في تيليجرام — عن قصد.)

### تمرين الاستعادة (افعلها مرة واحدة على الأقل)

نسخة لم تُجرَّب ليست نسخة. جرّب على حالة متجاهلة:

```bash
export AI_OS_DATA_DIR="$(mktemp -d)"      # مجلد مؤقت — لا تلمس الحالة الحقيقية
cp data/state.json "$AI_OS_DATA_DIR"/     # حالة للاختبار
python3 -m connectors.supabase_state push --reason "تمرين"
python3 -c "import json,os;p=os.path.join(os.environ['AI_OS_DATA_DIR'],'state.json');d=json.load(open(p));d['tasks']=[];json.dump(d,open(p,'w'))"
python3 -m connectors.supabase_state restore --id <رقم_النسخة> --apply
python3 -m connectors.supabase_state show --id <رقم_النسخة>   # ✅ سليمة
```

---

## 6️⃣ حل المشاكل

| الرسالة | السبب | الحل |
|---|---|---|
| `SUPABASE_URL يبدو رابط لوحة التحكم` | لُصق رابط المتصفح | استخدم `https://<ref>.supabase.co` |
| `HTTP 401 · المفتاح غير صحيح` | مفتاح تالف/من مشروع آخر، أو لصق ناقص | انسخه من **Settings → API Keys** كاملًا |
| `HTTP 404 · relation does not exist` | لم يُشغَّل SQL الإعداد | `python3 -m connectors.supabase_client --sql` |
| `HTTP 403 · RLS منعت العملية` | مفتاح عام يحاول الكتابة | استخدم المفتاح السري (خادم فقط) |
| `الكتابة في Supabase مغلقة` | الحاجز مقصود | `SUPABASE_WRITE_ENABLED=1` |
| `الكتابة تحتاج مفتاحًا سريًا` | المفتاح الحالي publishable/anon | ضع `SUPABASE_SERVICE_ROLE_KEY` |
| `بصمة sha256 لا تطابق الحمولة` | الصف تغيّر بعد الكتابة | لا تستعده؛ اختر نسخة أحدث |
| `Supabase غير مضبوط` في تيليجرام | Railway بلا متغيرات | اضبط الثلاثة ثم أعد النشر |

---

## 7️⃣ ما لا يفعله هذا (بعد)

- **لا ينقل مصدر الحقيقة إلى Supabase** — `state.json` هو المرجع، وهذا مقصود.
- **لا يخزّن معرفة/متجهات (pgvector)** — طبقة RAG كما هي؛ تُضاف لاحقًا عند حاجة فعلية.
- **لا يفتح لوحة ويب** — للوحة قراءة لاحقًا: أضف سياسة RLS ضيّقة على جدول مستقل
  بالمفتاح العام، ولا تكشف جدول النسخ (`payload` يحتوي حالتك كاملة).
- **لا ينسخ تلقائيًا في كل تعديل** — الدفع يدوي/أمر صريح، فلا ضجيج ولا تكلفة بلا داع.

### الخطوات التالية المقترحة عند الحاجة الفعلية

1. `state_snapshots` فقط + `/backup_now` مرة يوميًا (يدويًا) — ابدأ هنا.
2. جدولة تلقائية: أضف مهمة في `engine/scheduler.py` تنادي `supabase_state.push`
   مرة يوميًا 06:00 (بعد نجاح `backup_verify`) — بتكلفة صفرية تقريبًا.
3. لوحة قراءة على الجوال: جدول مستقل + سياسة RLS للقراءة العامة للأعمدة غير الحساسة.

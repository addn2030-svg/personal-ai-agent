# 🧠 الدماغ الدائم — ذاكرة الوكيل خارج الخادم

كيف تنجو ذاكرة الوكيل من إيقاف الخدمة أو استبدال المضيف، بلا متجهات وبلا حصة API إضافية.

---

## 1) المشكلة الحقيقية (ليست «الحالة»)

استمرارية الحالة **محلولة بالفعل**: `data/state.json` يُستعاد عند الإقلاع ويُدفع
تفاضليًا إلى Supabase (`connectors/state_persistence.py`). لكن الذاكرة كانت في مكان آخر
لم تشمله أي نسخة:

```text
data/memory/
├── working.json      ← سياق قصير العمر (TTL 24h)
├── episodic.jsonl    ← «ماذا جرى»: ملخّصات الجلسات والقرارات
└── semantic.jsonl    ← «ما نعرفه»: حقائق مثبتة بمصدر وثقة
```

على مضيف بلا قرص دائم (Render المجاني: `/tmp` فقط) **تُمحى هذه الملفات عند كل إيقاف
أو إعادة نشر**. النتيجة العملية: البوت يستيقظ، يستعيد مهامه وقراراته (من `state.json`)،
لكنه **فقد الحلقات والحقائق** ولا يستطيع الإجابة عن «ماذا ناقشنا في العقد؟» إلا من
آخر 60 سطرًا في `conversation_memory`.

الفرق بين الطبقتين:

| الطبقة | ما تحمله | مكانها قبل | بعد |
|---|---|---|---|
| استمرارية الحالة | `state.json`: مهام · قرارات · طوابير · حلقات استباقية | Supabase `state_snapshots` | كما هي (لم تُلمَس) |
| **الدماغ الدائم** | حلقات · حقائق · ذاكرة عاملة | ملفات محلية فقط | **جداول دائمة + الملفات المحلية كطبقة أولى** |

> `state.json` يبقى **مصدر الحقيقة الوحيد** للعمل التشغيلي. الدماغ طبقة **مشتقّة**:
> لو حُذفت كل صفوفه، النظام يعمل بلا تغيير — فقط تقلّ جودة التذكّر. هذا مقصود:
> لا مصدران للحقيقة، فلا «حجز مزدوج».

---

## 2) لماذا بلا متجهات (no pgvector)؟

`docs/agent3-p0-adjudication.md` أجّل pgvector حرفيًا: *«Defer pgvector حتى تبرّره أدلة
تشغيلية»*. الأدلة التي ظهرت فعلًا هي:

1. **ضياع الذاكرة عند تبديل المضيف** ← هذا يبرّر **متانة** التخزين.
2. **استرجاع عربي ضعيف بالتطابق الحرفي** ← هذا يبرّر **تطبيعًا لغويًا** لا تضمينًا.

ما لم يظهر بعد: حجم بيانات يبرّر تكلفة التضمين، ولا دليل على أن التشابه الدلالي
المتجهي يتفوّق على التطبيع + التشابه الثلاثي في هذا الاستخدام. لذلك الطبقة:

- تُطبّع العربي **بنفس قواعد** `engine/context_service.py` (`normalize()`) لكن داخل
  Postgres (`brain_fold`)، فالترتيب متسق بين المسارين.
- تسترجع بترتيب مرجّح: عدد الرموز المطابقة + تشابه ثلاثي (`pg_trgm`) + ثقة الحقيقة،
  مع تنزيل الحقائق المُبطَلة (`superseded_by`) لا حذفها.

**الترقية إلى pgvector لاحقًا لا تفقد شيئًا**: أضف عمود `embedding` إلى نفس الجدولين
وفهرس HNSW، ولا تتغير إلا دالة `brain_recall` — البقية كما هي.

---

## 3) المعمارية

```text
                    كتابة (محليًا أولًا، دائمًا)
   البوت/المدير ──▶ data/memory/*.jsonl ──┐
                                          │  مرآة عند تفعيل BRAIN_WRITE_ENABLED
                                          ▼
                              Supabase: brain_episodes · brain_facts · brain_working

                    استرجاع (سحابي، مع سقوط آمن)
   سؤال المستخدم ──▶ brain_recall() ──┬─ نجح ──▶ كتلة «DURABLE BRAIN RECALL» في السياق
                                      └─ فشل ──▶ استرجاع محلي بلا ضجيج
```

نقاط الاتصال الثلاث (كلها إضافية، ولا واحدة منها تعدّل مسار عمل قائمًا):

| الموضع | ماذا يفعل |
|---|---|
| `engine/agent_runtime.build_context()` | يحقن `brain.recall_context(query)` **مبكرًا** في السياق (قبل قطع `MAX_CONTEXT_CHARS`) |
| `engine/agent_runtime.remember()` | يرآي كل دور محادثة (بعد بوابة الحجم) كـ`episode` |
| `connectors/telegram_webhook_runtime_memory.py` | `/brain_status` و`/brain_recall` للجوال |

---

## 4) الإعداد (خمس دقائق)

### الخطوة 1 — الجداول في Supabase (مرة واحدة)

```bash
python3 -m connectors.brain --sql        # يطبع SQL جاهزًا للنسخ
```

ثم: Supabase → **SQL Editor** → New query → Run. (أو الصق محتوى
`supabase/03_brain_memory.sql` مباشرة.)

ما يُنشئه: `brain_episodes` · `brain_facts` · `brain_working` · `brain_norm`/`brain_fold`
· `brain_recall()` · `brain_stats()` · `brain_prune()` — مع RLS مفعّل وبلا أي سياسة،
و`revoke all` عن `anon` و`authenticated`، تمامًا كجدولي `state_snapshots` و`tasks_mirror`.

### الخطوة 2 — الرايات (مغلقة افتراضيًا)

| المتغير | القيمة | الأثر |
|---|---|---|
| `BRAIN_ENABLED` | `1` | يسمح بأي نداء شبكي. بدونه الطبقة خاملة تمامًا |
| `BRAIN_RECALL_ENABLED` | `1` | يحقن الاسترجاع في سياق الردود |
| `BRAIN_WRITE_ENABLED` | `1` | يرآي الكتابات المحلية (يحتاج المفتاح السري + `SUPABASE_WRITE_ENABLED=1`) |

اختيارية (لها قيم افتراضية معقولة):

| المتغير | الافتراضي | الغرض |
|---|---|---|
| `BRAIN_RECALL_ITEMS` | `6` | عدد العناصر المحقونة في السياق |
| `BRAIN_RECALL_CHARS` | `3000` | أقصى طول لكتلة الاسترجاع |
| `BRAIN_RECALL_TIMEOUT_SECONDS` | `6` | مهلة الاسترجاع — **أقصر من مهلة التخزين** لأن سؤال المستخدم لا ينتظر Supabase |
| `BRAIN_RECALL_FAILURES` | `3` | عدد الإخفاقات المتتالية قبل فتح قاطع الدائرة |
| `BRAIN_RECALL_COOLDOWN_SECONDS` | `120` | مدة التخطّي بعد فتح القاطع |

على Render كلها مضبوطة في `render.yaml`. على أي مضيف آخر: Service → Environment.

### الخطوة 3 — التحقق

```bash
python3 -m connectors.brain --status     # بلا شبكة: ما المضبوط وما الناقص
python3 -m connectors.brain --live       # فحص حي + إحصاء الجداول
```

من تيليجرام: `/brain_status`.

### الخطوة 4 — ترحيل الذاكرة الحالية (اختياري لكن مُستحسن)

```bash
python3 -m connectors.brain --import                    # ملفات الذاكرة + المحادثة
python3 -m connectors.brain --import --without-conversations
```

- يقرأ `episodic.jsonl` · `semantic.jsonl` · و`conversation_memory` من `state.json`.
- **idempotent**: المعرّفات حتمية والرفع `upsert` ⇒ إعادة التشغيل لا تُكرّر شيئًا.
- **يستبعد المحتوى الحساس** (`clinical_private` / `restricted`) ويعدّه في تقريره.

---

## 5) نموذج السلامة

| القاعدة | أين تُطبَّق |
|---|---|
| مطفأ افتراضيًا | `BRAIN_ENABLED` — لا شيء يُرسل لمجرد وجود المفاتيح |
| الكتابة تحتاج **ثلاثة شروط** | مفتاح سري **و**`SUPABASE_WRITE_ENABLED=1` **و**`BRAIN_WRITE_ENABLED=1` |
| المفتاح العام لا يكتب | `supabase_client.can_write` — مفتاح `publishable`/`anon` يُرفض دائمًا |
| **المحتوى السريري لا يغادر الخادم** | `NEVER_REMOTE = {clinical_private, restricted}` في `brain.py` — تُكتب محليًا وتُتخطّى المرآة ويُسجَّل `brain_mirror_skipped` |
| الاسترجاع لا يُظهر الحساس افتراضيًا | `brain_recall(..., include_sensitive=false)` ⇒ العادي والداخلي فقط |
| لا سرّ في أي مخرَج | كل رسالة خطأ تمر بـ`redact()` قبل العرض |
| لا كتابة من الجوال | `/brain_recall` قراءة فقط؛ الرفع الجماعي من الطرفية |
| القراءة محجوبة عن العام | RLS مفعّل بلا سياسات + `revoke all` عن `anon`/`authenticated` |

---

## 6) الفشل والأعطال (سلوك مقصود لا مفاجأة)

| الحالة | ما يحدث |
|---|---|
| Supabase متوقف أو الشبكة مقطوعة | الاسترجاع يعود محليًا فورًا، والكتابة تُنجح محليًا، والسبب يُسجَّل في `audit.jsonl` |
| Supabase بطيء (مهلة في كل سؤال) | **قاطع دائرة**: بعد 3 إخفاقات متتالية يتوقف الاسترجاع الشبكي 120 ثانية (يُسجَّل `brain_recall_breaker_open`)، ثم يعود تلقائيًا — فلا يدفع كل سؤال ثمن شبكة ميتة |
| الجداول غير مُنشأة | `--status` يقول: شغّل `supabase/03_brain_memory.sql` (يعرض تلميح الكود `42P01`) |
| مفتاح خاطئ أو منتهٍ | فحص `--status` يسمّي الناقص بدقة وبلا طباعة المفتاح |
| `state.json` مفقود عند الترحيل | الترحيل يتخطّى قسم المحادثة بلا خطأ (يحذّر في التقرير) |
| ضغط بيانات | `python3 -m connectors.brain --prune 2000` — يُبقي أحدث 2000 حلقة، **ولا يحذف حقيقة** (الإبطال `superseded_by` هو أداة التقادم) |

**التراجع الكامل** بلا فقدان بيانات: اضبط `BRAIN_ENABLED=0`. تعود الطبقة خاملة،
وتبقى الملفات المحلية كما هي، و`state.json` لم يُلمَس أصلًا.

---

## 7) الأوامر

```bash
python3 -m connectors.brain --status      # الحال (بلا شبكة)
python3 -m connectors.brain --check       # نفس الفحص بإخراج مختصر
python3 -m connectors.brain --sql         # SQL الإعداد
python3 -m connectors.brain --live        # فحص حي + إحصاء
python3 -m connectors.brain --recall "العقد مع العمير"
python3 -m connectors.brain --import      # ترحيل الذاكرة المحلية
python3 -m connectors.brain --stats
python3 -m connectors.brain --prune 2000
```

من تيليجرام: `/brain_status` · `/brain_recall <كلمات>`

من SQL Editor مباشرة (مفيد للتحقق اليدوي):

```sql
select * from public.brain_recall('العقد مع العمير', 10, false);
select public.brain_stats();
```

---

## 8) ما تغيّر في النظام

| الملف | التغيير |
|---|---|
| `supabase/03_brain_memory.sql` | جديد — الجداول والدوال والفهارس والحماية |
| `connectors/brain.py` | جديد — الموصل: استرجاع · مرآة · ترحيل · إحصاء · تقليم |
| `engine/agent_runtime.py` | حقن الاسترجاع في السياق + مرآة الأدوار + إصلاح مسار الذاكرة |
| `engine/memory.py` · `engine/rag.py` | **إصلاح**: احترام `AI_OS_DATA_DIR` (كانا يكتبان في جذر المستودع، فينقسم المخزن على مجلدين على مضيف بلا قرص) |
| `connectors/telegram_webhook_runtime_memory.py` | `/brain_status` · `/brain_recall` + سطر إقلاع يعلن حالة الطبقة |
| `render.yaml` · `.env.example` | رايات الدماغ وشرحها |
| `.gitignore` | `data/memory/` — ملفات ذاكرة شخصية لا تدخل Git أبدًا |
| `tests/test_brain.py` | 34 اختبارًا: الخمول · البوابة الثلاثية · منع السريري · السقوط الآمن · منع تسرّب المفاتيح · مسار التخزين |

---

## 9) الفحص الذاتي للمشكّك

الاختبارات تثبت **أن الفحوص قادرة على الفشل**، لا أنها خضراء فقط:

```bash
python3 -m unittest tests.test_brain -v
```

وأهم ثلاثة أسئلة تُختبر صريحًا:

1. هل يمكن أن تُرسَل بيانات إلى السحابة بلا راية؟ **لا** —
   `test_write_flags_alone_do_not_enable_cloud_writes`.
2. هل يمكن أن يغادر محتوى سريري؟ **لا** —
   `test_clinical_episode_is_written_locally_and_never_mirrored`.
3. هل يسقط الرد إذا فشلت الذاكرة؟ **لا** —
   `test_agent_runtime_brain_context_never_raises`.

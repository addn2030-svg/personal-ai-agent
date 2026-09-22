# 🚚 نقل التشغيل: Railway (حساب منتهٍ) → Render المجاني + Supabase

دليل تنفيذي لحالتك تحديدًا: حساب Railway انتهى، والاستمرارية تصبح **شرط تشغيل لا رفاهية**.
الهدف: وكيل يعمل بـ$0، ولا يفقد ذاكرته ولا مهامه عند أي إيقاف أو إعادة نشر.

> **قبل أي شيء — مؤقت 30 يومًا:** عند انتهاء تجربة Railway تُوقف الحاويات **فورًا**،
> وبيانات الـVolume تبقى **30 يومًا ثم تُحذف نهائيًا**. إن كنت ستستعيد حالة قديمة فالعملية
> محصورة في هذه النافذة. وإن اخترت البدء نظيفًا (وهو الأسرع) فاقرأ القسم 2 مباشرة.

---

## 0) ما أستطيع وما لا أستطيع فعله نيابة عنك

| العمل | من ينفّذه |
|---|---|
| كتابة الملفات والاختبارات وتعديل `render.yaml` وSQL | ✅ تم في هذا المستودع |
| مشاركة لوحة Railway أو ربط GitHub من لوحة Railway | ❌ يحتاج دخولك: لا أصل إلى حسابك، ولا يجب أن أطلب مفاتيحك |
| إنشاء حساب Render وربط المستودع | ❌ لوحتك |
| مشروع Supabase (URL + مفتاح سري) | ❌ لوحتك — والقيم سرّية لا تمر عبر محادثة |

الخطوات في الأقسام التالية مصمَّمة لتكون **نسخ/لصق وضغط أزرار** بلا تفكير إضافي.

---

## 1) قرار سريع: هل تستعيد حالة Railway القديمة؟

| الحالة | ماذا تفعل | التكلفة |
|---|---|---|
| لا تحتاج المهام/القرارات القديمة | تجاوز هذا القسم — ابدأ نظيفًا | $0 |
| تحتاجها | ترقية Railway إلى **Hobby ($5)** لشهر واحد، فتُستأنف الخدمة ويُقرأ الـVolume | ~$5 لمرة واحدة |

**كيف تستعيدها (إن اخترت ذلك) قبل الإغلاق:**

1. Railway → Workspace → **Billing** → Hobby.
2. المشروع → الخدمة → **Deploy** (أو أعد المحاولة) لتعمل الحاوية ببياناتها.
3. من طرفية الخدمة (Railway → الخدمة → Shell/SSH):

   ```bash
   python3 -m connectors.supabase_state push --reason "قبل إغلاق Railway"
   ```

   يرفع `state.json` الموقّع بـsha256 إلى Supabase. وإن أردت نسخة على جهازك:

   ```bash
   python3 -m connectors.supabase_state pull --id latest
   ```

4. تأكد أن `supabase_state list` يُظهر نسخة بتاريخ اليوم، ثم **ألغِ ترقية Railway**.
5. لاحقًا على Render: لا تفعل شيئًا — `AI_OS_STATE_RESTORE_ON_BOOT=1` يستعيدها تلقائيًا عند أول إقلاع.

> الاحتياط الإلزامي: **لا تحذف خدمة Railway قبل اكتمال الخطوة 4.** حذف الخدمة يحذف الـVolume،
> ولا تُستعاد البيانات بعده بأي طريقة.

### إعادة ربط Railway بالمستودع (إن أردت إبقاءه كخط ثانٍ)

Railway → **New Project** → **Deploy from GitHub repo** → اختر
`addn2030-svg/personal-ai-agent`. إن لم يظهر المستودع فثبّت **Railway GitHub App** على
الحساب وامنحه وصولًا لهذا المستودع فقط، ثم أعد المحاولة.
ولمشاركة المشروع مع بريد آخر: **Project → Settings → Members → Invite**
(`hawsawia@rchsp.med.sa`). العضوية في Railway لا تنقل إعدادات خدمتك؛ كل عضو يرى ما يخص
مساحة العمل التي دُعي إليها.

⚠️ على خطة Free بعد التجربة: مشروع واحد، 3 خدمات، قرص 0.5GB، ورصيد $1/شهر. الخدمة
الدائمة تحتاج Hobby أصلاً — وهذا سبب كافٍ للانتقال إلى Render مع Supabase كقرص.

---

## 2) Supabase هو القرص (مرة واحدة، ~10 دقائق)

Render المجاني **بلا قرص دائم**: كل ما يُكتب داخل الحاوية يُفقد عند النوم أو النشر.
لذلك Supabase ليس «تحسينًا» هنا، بل هو مكان الحالة والذاكرة.

1. `supabase.com` → مشروع جديد (الخطة المجانية).
   تحذير الخطة المجانية: المشروع **يُوقَف بعد 7 أيام خمول** ولا نسخ احتياطي تلقائي ولا PITR —
   ولهذا يوجد أمر `pull` لتنزيل نسخة على جهازك.
2. **Connect** أو **Settings → API Keys** → انسخ `Project URL` والمفتاح السري `sb_secret_…`.
3. **SQL Editor** → شغّل المخططات الثلاثة بالترتيب:

   ```bash
   python3 -m connectors.supabase_client --sql          # 1) state_snapshots
   python3 -m connectors.supabase_client --sql tasks    # 2) tasks_mirror
   python3 -m connectors.brain --sql                    # 3) دماغ الذاكرة الدائم
   ```

4. ضع المفاتيح في لوحة Render (لا في Git ولا في محادثة):

   | المتغير | القيمة |
   |---|---|
   | `SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | المفتاح السري — خادم فقط |
   | `SUPABASE_WRITE_ENABLED` | `1` (موجود مسبقًا في `render.yaml`) |

---

## 3) النشر على Render (Blueprint)

1. `render.com` → **New** → **Blueprint** → اختر `addn2030-svg/personal-ai-agent`
   (وثبّت **Render GitHub App** وامنحه هذا المستودع إن لم يظهر).
2. Render يقرأ `render.yaml` ويبني الخدمة تلقائيًا: Docker · `plan: free` ·
   `healthCheckPath: /health` · `region: frankfurt`.
3. سيعرض لك تعبئة المتغيرات التسعة `sync: false`. الضروري للعمل:

   | المتغير | من أين |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | BotFather |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud → Service Account (JSON كامل كقيمة واحدة) |
   | `GOOGLE_SHEET_ID` | رابط الشيت التشغيلي |
   | `GEMINI_API_KEY` | Google AI Studio |
   | `SUPABASE_URL` · `SUPABASE_SERVICE_ROLE_KEY` | الخطوة 2 |

   والباقي اختياري (`CLINICAL_SHEET_ID` · `GOOGLE_CALENDAR_ID` · `GITHUB_TOKEN` ·
   `KIMI_API_KEY` · `BUFFER_API_KEY` · `DRIVE/DOCS`).
4. `TELEGRAM_WEBHOOK_BASE_URL` — **اتركه فارغًا**: الكود يكتشف
   `RENDER_EXTERNAL_HOSTNAME` تلقائيًا. وإن ملأته فليكن الرابط الفعلي
   `https://<اسم-الخدمة>.onrender.com` بلا شرطة أخيرة (رابط خاطئ يسجّل webhook إلى خدمة ميتة).
5. **Create** ثم راقب السجل. أول سطر يجب أن يكون:

   ```text
   AI-OS runtime boot: entrypoint reached
   State restore on boot: ...
   Durable brain: active | read=True write=True recall=True | commands=/brain_status,/brain_recall
   ```

   إن ظهر `Durable brain: DORMANT` فراجع رايات `BRAIN_*` في القسم 2 من
   `docs/brain-durable-memory.md`.

---

## 4) تحويل تيليجرام وGoogle إلى العنوان الجديد

| المزوّد | العمل |
|---|---|
| **Telegram** | لا تفعل شيئًا يدويًا: الخدمة تسجّل الـwebhook عند الإقلاع. تحقق من `/time` في البوت |
| **Google Sheets/Drive/Docs/Calendar** | شارك كل ملف/تقويم مع `client_email` داخل `GOOGLE_SERVICE_ACCOUNT_JSON` بصلاحية Editor (التقويم: «إجراء تغييرات على الأحداث») |
| **Gemini** | لا شيء — المفتاح نفسه |
| **GitHub** | لا شيء للمستودع العام |

---

## 5) مشكلة النوم (15 دقيقة) — الحل والحساب

الخدمة المجانية تنام بعد 15 دقيقة بلا حركة، والإقلاع 30-60 ثانية. لتيليجرام هذا يعني أن
أول رسالة بعد نوم طويلة قد تتأخر أو تفشل.

**الحل الجاهز في المستودع**: `.github/workflows/keepalive.yml` يفحص `/health` كل 10 دقائق
خلال **07:00–24:00 بتوقيت الرياض** فقط.

| الخيار | الساعات/شهر | الحكم |
|---|---|---|
| ping على مدار الساعة | ~744 | يستهلك الرصيد كله (750) بلا هامش — وإن نضب تُوقف Render **كل** الخدمات حتى أول الشهر |
| **النافذة المضبوطة في الملف** | **~527** | ✅ التوصية: يغطي ساعات العمل مع هامش آمن |
| بلا ping | 0 | البوت ينام — استخدمه إن كان الاستخدام متقطعًا فقط |

لتفعيله: GitHub → Settings → Secrets and variables → Actions → **Variables** →
`RENDER_HEALTH_URL = https://<اسم-الخدمة>.onrender.com/health`.
بلا هذا المتغير لا يفعل الملف شيئًا (خامل بأمان).

---

## 6) التحقق بعد النشر

```bash
curl -fsS https://<اسم-الخدمة>.onrender.com/health     # 200 دائمًا
curl -i   https://<اسم-الخدمة>.onrender.com/ready      # غير 200 حتى تكتمل صلاحيات Google
```

من تيليجرام:

```text
/time            ← الوقت + فحص فوري
/selftest        ← فحص كامل للقنوات
/storage_status  ← حفظ Google Sheets
/brain_status    ← طبقة الذاكرة الدائمة
/brain_recall مسودة العقد    ← استرجاع فعلي من الذاكرة
```

**اختبار المتانة (الأهم):** أعد نشر الخدمة من Render (**Manual Deploy → Deploy latest**),
ثم تحقق من:

1. `/brain_status` — الأعداد السحابية لم تنقص.
2. المهام والقرارات كما هي (`/tasks` أو `/brief`).

إن نجح ذلك فأنت فعلًا بلا قرص، ومع ذلك بلا فقدان بيانات.

---

## 7) ترحيل الذاكرة القديمة (إن وُجدت)

على المسار المحلي القديم (أو داخل خدمة Railway بعد استئنافها):

```bash
python3 -m connectors.brain --import      # idempotent — إعادة التشغيل آمنة
```

يقرأ `data/memory/*.jsonl` + `conversation_memory` من `state.json`، ويستبعد المحتوى
السريري تلقائيًا.

---

## 8) التراجع — بلا فقدان

| الحالة | الإجراء |
|---|---|
| خطأ في طبقة Supabase | `BRAIN_ENABLED=0` — تعود الطبقة خاملة والنظام يعمل على الملفات المحلية |
| خطأ في أتمتة النسخ | `/rollout_kill` من تيليجرام أو `python3 -m engine.rollout kill` |
| تلف الحالة بعد نشر | `python3 -m connectors.supabase_state restore --id N --apply` |
| استمرار مشكلة Render | Fly.io بـ~$2/شهر بنفس المستودع و`Dockerfile` — لا تغيير في الكود |

**قاعدة واحدة تحكم كل ما سبق:** لا شيء من هذه الخطوات يحذف بيانات. الإيقاف يوقف أتمتة،
والاستعادة تكتب نسخة إضافية، والتراجع لا يمحو صفًا.

# 🕰️ التوقيت التلقائي (Automatic Timing) — v1.1

> آخر ما كان ناقصًا في v1.0: المحركات كانت **جاهزة لكنها لا تعمل وحدها** على
> الخادم. `manager.py --loop` يشتغل على الجهاز الشخصي (systemd/launchd/Task
> Scheduler)، أما حاوية الإنتاج (Railway) فتشغّل وب تيليجرام فقط — بلا cron ولا
> حلقة مدير. هذا المرجع يوثّق الطبقة الجديدة: **`engine/timing.py`** التي تقرّر
> ما المستحق وتنفّذه، مع مُركِّب cron ومُركِّب systemd timer وخيط تشغيل داخل
> حاوية الإنتاج.

## 1. الجدول (ماذا يحدث الآن بلا أن تطلب)

| الوظيفة | `job_id` | الموعد الافتراضي | ما تفعله |
|---|---|---|---|
| ☀️ بريف الصباح | `timing.morning_brief` | يوميًا **06:30** | دورة استباقية ← `reports/proactive-brief-YYYY-MM-DD.md` ← رسالة الصباح للمحادثة المالكة |
| 🛰️ المسح الدوري | `timing.periodic_sweep` | **كل 3 ساعات** | `manager.fast_cycle()` (متأخرات/انتهاء صلاحيات/طلبات قرار) + `scheduler.dispatch_due()` (مسودات محرك الأتمتة) + `proactive.sweep()` |
| 🔬 أهداف البحث | `timing.research_goals` | **يوميًا 05:40** | `research_goals.run_due()`: كبسولة لكل هدف مستحق + ترويج المُلحَق — **تُتخطّى تلقائيًا إن لا أهداف مسجَّلة** ([v1.2](research-goals.md)) |
| 📊 مراجعة الأسبوع | `timing.weekly_review` | **الأحد 07:00** | `proactive.review_text()` (معدل القبول/التراجع/امتلاء السقف) + ضبط العتبات إن فُعّل `TIMING_REVIEW_APPLY=1` |

المواقيت بتوقيت `MANAGER_TIMEZONE` (الافتراضي Asia/Riyadh) **لا بتوقيت الخادم** —
وهذا سبب التوصية بوضع «النبضة» (Bند 3) بدل سطور cron مقيدة بالساعة.

06:30 ليست اعتباطية: ساعات الهدوء في محرك الاستباقية 22:00–06:30، فالبريف يأتي
فور انتهائها، وتكون تنبيهات المساء المتأخرة والملخّصة قد دخلت البريف لا الجوال.

## 2. أين تسكن الحقيقة

| الشيء | المكان |
|---|---|
| جدول الوظائف والعتبات | `engine/timing.py` (`JOB_SPECS` + `cfg()`) |
| دفتر تشغيل الجدولة (من جرى، متى، لماذا فشل) | قسم `timing_runs` في `data/state.json` |
| علامة النبض اليومي (دليل أن cron حيّ) | `manager_markers.timing_heartbeat_day` |
| سجل التدقيق | `data/audit.jsonl`: `timing_run` · `timing_job_error` · `timing_lock_error` · `timing_worker_started/_error` |
| قفل عدم التراكب | `data/.timing.lock` (flock/msvcrt، غير متتبَّع في Git) |
| المسودات الناتجة | طابور الاعتماد `action_queue` كالمعتاد — **لا قناة ثانية** |

مبدأ الحوكمة لم يتغيّر: التوقيت التلقائي **لا يرسل ولا ينفّذ خارجيًا أبدًا**. كل
ما يمس الخارج يبقى مسودة `PENDING_APPROVAL` خلف `engine/approve.py`. القناة
الخارجية الوحيدة هي رسالة نصية للمحادثة المالكة عبر قناة تنبيهات الاستباقية
نفسها، وتُعطَّل بـ `TIMING_PUSH=0` (أو `PROACTIVE_TELEGRAM_PUSH=0`).

## 3. خادم فيه cron (VPS/صندوق داخلي) — التوصية

```bash
bash autostart/cron/install.sh          # نبضة كل 5 دقائق + نبضة عند الإقلاع
```

ما يُركَّبه (بوسم `AIOS-TIMING` حتى تبقى بقية crontab كما هي):

```cron
*/5 * * * * /path/to/repo/scripts/aios-timing.sh tick
@reboot sleep 30 && /path/to/repo/scripts/aios-timing.sh tick
```

**لماذا نبضة كل 5 دقائق والقرار للمحرّك، بدل `30 6 * * *`؟** لأن المحرّك:

- **يلحق الفائت (catch-up):** إن كان الخادم نائمًا/مطفأًا 06:30، أول نبضة بعده
  تولّد بريف اليوم مرة واحدة فقط (مفتاح الدورة = التاريخ).
- **لا يكرّر:** التنفيذ الناجح يسجَّل بـ `cycle_key` (اليوم للبريف، أحد الأسبوع
  للمراجعة) فأي نبضة إضافية لاحقًا لا تفعل شيئًا — ولا تكتب في الحالة أصلًا.
- **يمنع التراكب:** قفل عملية غير حاجز؛ إن كانت دورة سابقة ما تزال جارية تعود
  النقرة الجديدة بحالة `busy` وخرج 0 (بلا بريد cron).
- **يتراجع أمام الفشل:** وظيفة تفشل ← رجوع أُسّي يبدأ من `TIMING_RETRY_MINUTES`
  (20 د) ويتضاعف حتى ~21 ساعة، لا إعادة محاولة كل 5 دقائق.

الغلاف `scripts/aios-timing.sh` يدخل بمجلد المستودع، يقرأ `.env` إن وُجد، يختار
`python3` المناسب، ويكتب/يدوّر `logs/timing.log`. لذلك **لا تُضِف** `>> log 2>&1`
إلى السطر لئلا تتكرر الأسطر.

### بديل: سطر cron لكل وظيفة (دقّة cron الأصلية)

```bash
python3 engine/timing.py install-cron --mode native          # يطبعها
python3 engine/timing.py install-cron --mode native --write  # يركّبها
bash autostart/cron/install.sh --native
```

تولَّد من نفس مصدر الحقيقة (مواقيت البيئة + المسارات + الوسم)، وتُنَبّهك إن
اختلفت ساعة الخادم عن منطقة الجدولة. عيبها الوحيد: تفوّت الوظيفة إن كان cron
متوقفًا تلك الدقيقة بالذات.

### بديل: systemd timer (حين لا يوجد crontab)

```bash
bash autostart/cron/install.sh --timer      # aios-timing.timer كل 5 دقائق + Persistent=true
bash autostart/cron/remove.sh               # يزيل crontab الموسوم والوحدتين معًا
```

`Persistent=true` يمنح نفس خاصية اللحاق بالفائت التي يوفرها المفتّح في المحرّك.

## 4. حاوية إنتاج بلا cron (Railway) — خيط داخل العملية

الصورة لا تحتوي `cron`، لذا تُدار الجدولة داخل عملية الـ webhook نفسها عبر
`connectors/timing_worker.py` (نفس عقد `manager_fast_canary`: خيط daemon،
fail-soft، ولا كتابة إن لا شيء مستحقًا):

```python
timing_worker.start_if_enabled()   # تُنادى من connectors/telegram_webhook.run()
```

| المتغير | الافتراضي | المعنى |
|---|---|---|
| `AIOS_TIMING_WORKER` | `1` | تشغيل/إيقاف الخيط داخل الحاوية فقط |
| `AIOS_TIMING_ENABLED` | `1` | مفتاح المحرك الكامل (يوقف cron والخيط معًا) |
| `TIMING_TICK_SECONDS` | `300` | دورية النبض (أرضية 15 ث) |

سطر بدء التشغيل المطبوع في السجل يثبت أنها تعمل:

```
Automatic timing worker: active | heartbeat=300s | brief=06:30 | sweep=every 3h | review=07:00 (weekdays=6)
```

ويظهر أيضًا في `GET /health` تحت `automatic_timing` (عدد النبضات، الوظائف
المنفّذة، آخر خطأ) — فلا حاجة لفتح الطرفية للتحقق.

**تشغيل cron والخيط معًا آمن:** مفتاح الدورة + قفل الحالة + `write-on-change`
تجعل الدورة الثانية لا تفعل شيئًا. ومع ذلك يُنصح بواحد فقط: الخيط على الحاوية،
cron على الخادم الدائم.

## 5. العتبات والبيئة الكاملة

```bash
TIMING_BRIEF_AT=06:30              TIMING_BRIEF_ENABLED=1
TIMING_SWEEP_INTERVAL_HOURS=3      TIMING_SWEEP_ENABLED=1
TIMING_REVIEW_AT=07:00             TIMING_REVIEW_WEEKDAY=6   # 0=الاثنين .. 6=الأحد
TIMING_REVIEW_DAYS=7               TIMING_REVIEW_APPLY=0
TIMING_PUSH=1                      TIMING_RETRY_MINUTES=20
AIOS_TIMING_ENABLED=1              AIOS_TIMING_WORKER=1
MANAGER_TIMEZONE=Asia/Riyadh       AI_OS_DATA_DIR=/data
```

تُقرأ في كل نداء (`cfg()`)، فتغييرها في البيئة يسري من النبضة التالية بلا إعادة
بناء. للتجربة بلا تعديل المنصة: `pause` من محرك الاستباقية يوقف دورات sweep
وحده، و`AIOS_TIMING_ENABLED=0` يوقف الجدولة كلها.

## 6. التحقق — أمر واحد يعطي برهانًا كاملاً

```bash
python3 engine/timing.py verify          # نص يُرمى في الرد كما هو (exit 0 سليم / 1 عطل)
python3 engine/timing.py verify --json    # للنسخ الآلي أو لوحة المراقبة
```

يفحص 13 بندًا بطبقاتها، ويضع تحت كل بند معطّل سطر إصلاح:

| الطبقة | البنود | الحكم |
|---|---|---|
| الأعلام | `engine` (AIOS_TIMING_ENABLED) · `worker` (AIOS_TIMING_WORKER) | ❌ إن كان المحرّك موقوفًا |
| الساعة | `timezone` (فرق ساعة الخادم عن منطقة الجدولة) · `schedule` (المواقيت الفاعلة) | ⚠️ فرق ساعة لا يهمّ وضع tick ويهمّ native |
| النبض | `heartbeat` (نبض اليوم) · `runs` (عدد تشغيلات اليوم) · `errors` (أخطاء اليوم) | ❌ إذا استحق شيء ولم يُنفَّذ؛ ⚠️ إن لم يستحق شيء بعد |
| المخرجات | `push` (قناة تيليجرام) · `brief_file` (ملف بريف اليوم) | ⚠️ قناة غائبة = ملفات فقط، لا فشل |
| التركيب | `installer` (سطر cron أو وحدة timer) · `data_dir` (قابل للكتابة) · `lock` (متاح الآن) · `state_schema` | ❌ مجلد غير قابل للكتابة أو قسم مفقود |

والنظر اليدوي عند الحاجة:

| ماذا | الأمر | النتيجة الدالة على الحياة |
|---|---|---|
| المحرّك يرى الجدول | `python3 engine/timing.py status` | `heartbeat_day` = اليوم، ووظيفة واحدة على الأقل `due_now` أو سبب انتظار منطقي |
| cron يركض فعلًا | `crontab -l \| grep AIOS-TIMING` و`logs/timing.log` | أسطر `── … aios-timing tick` + `exited rc=0` |
| الحالة شهدت بالتشغيل | `python3 -c "import json;print(json.load(open('data/state.json'))['timing_runs'][-3:])"` | صفوف بـ `status: ok` و`trigger: cron/loop/webhook-worker` |
| لا إرسال خارجيًا | `python3 engine/approve.py list` | كل ناتج الجدولة مسودة `PENDING_APPROVAL` |

### إعدادات الطبقة الاستباقية من الحالة (بلا إعادة نشر)

الجدولة تقرأ الحواجز من نفس المصدر الذي تُضبط منه، فتصحيح «لا ترفعني قبل 7» لا
يحتاج لمس متغيرات المنصة:

```bash
python3 engine/proactive.py config --quiet 23:00-07:00 --max-alerts 4
python3 engine/proactive.py config            # القيمة + مصدرها (state/env/default)
python3 engine/proactive.py config-clear      # رجوعًا إلى البيئة
```

ولتشغيل شيء الآن من جوالك بلا طرفية: `/timing_run` (المستحق) أو
`/timing_run brief` (بريف الصباح فورًا). للجدولة الكاملة القديمة: `/schedule`؛
لمراجعة الأسبوع وقبولك الحقيقي: `/review [days]`.

## 7. ما لا يفعله التوقيت التلقائي

- لا يرسل رسالة ولا ينفّذ إجراءً خارجيًا — المسودات فقط (القاعدة الحاكمة v4.1.1).
- لا يستبدل `manager.py --loop` على الجهاز الشخصي: حلقة المدير أوفى (كل 15
  دقيقة + دورة كاملة 06:00)؛ الجدولة هنا أدقّ ما يلزم للخادم. إن عمل الاثنان
  معًا فلا تكرار — لأسباب idempotency نفسها.
- لا يخترع وقتًا: «مستحق» = مرّ الموعد ولم يُنفَّذ في هذه الدورة.
- لا يكرّر بريف اليوم لو أعيد تشغيل الخادم عشر مرات.

## 8. الملفات والاختبارات

```
engine/timing.py                      ← المحرّك + CLI (list/status/tick/run/loop/install-cron)
connectors/timing_worker.py           ← خيط التشغيل داخل حاوية الإنتاج
scripts/aios-timing.sh                ← غلاف cron (بيئة · مجلد · سجل · دوران)
autostart/cron/aios-timing.crontab.template
autostart/cron/aios-timing.{service,timer}.template
autostart/cron/install.sh · remove.sh
```

الاختبارات: `python3 -m unittest tests.test_timing` (34) — قواعد الاستحقاق،
اللحاق بالفائت، idempotency، الرجوع عند الفشل، قفل التراكب، نص بريف الصباح،
توليد سطور cron، عقد الخيط، وصندوق `verify`، وأوامر البوت `/timing` `/timing_run` `/review`.
و`tests/test_proactive.py` (48) يغطي طبقة الإعدادات المخزّنة (أولوية الحالة على
البيئة، رفض النافذة الصفرية والإسكات، والأثر الفعلي على مسار التنبيه)،
و`tests/test_approve_draft.py` (6) يغطي إدخال المسودات إلى الطابور بالبصمة.
المرجع الشقيق: `docs/v1.0-proactive-chief-of-staff.md`.

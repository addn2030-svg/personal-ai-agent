# تدقيق: ماذا يُستخدم وماذا لا يُستخدم — الشيت الرئيسي مقابل المحرك الحالي
**التاريخ:** 15 سبتمبر 2026 (UTC) — **المنشأ:** `arena/01a0a62d`  
**الشيت المستهدف:** `1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc` (gid=92003) — **خاص، يتطلب تسجيل دخول Google**  
**المرآة المحلية المحللة:** `data/master-sheet.xlsx` (نفس المخطط 1:1 — يُستخدم كمصدر الاستيراد/التصدير للـ State Store) — 11 تبويب، 94 صف بيانات + 5 انتظار مُشتق → `data/state.json`

> **ملاحظة الوصول:** رابط Google Sheets أعلاه يعيد صفحة `accounts.google.com` (Sign-in). لا يمكن قراءته مباشرة دون جعله Public أو مشاركته مع Service Account. كل الأرقام أدناه من النسخة المحلية التي يبني عليها المحرك فعليًا (`engine/chief_of_staff.py` + `engine/migrate.py`). إذا كان الشيت الحي يحوي تبويبات إضافية (مثلاً `Executive_Brief` أو `PUBLISH_QUEUE`) فهي خارج هذا التدقيق — أخبرني لأفتحها لك.

---

## 1) الخلاصة التنفيذية — بجملة واحدة

**كل الأعمدة الـ 11 في الشيت الرئيسي مربوطة ومستخدمة فعليًا** في `chief_of_staff.py` و`manager.py` و`proactive.py` و`scheduler.py` — لكن **~18 ملف engine و~14 connector موجودون في المستودع ولا يُستدعون أبدًا في حلقة الإنتاج الحالية** (`manager --loop`). النظام الحالي يعمل بـ **حلقة ضيقة: `manager fast + chief + scheduler + proactive`** والباقي تراث مراحل v0.5–v0.8 / بنية مهارات لم تُفعّل.

**ما يعمل الآن (26 مهمة روتينية أنجزها المحرك اليوم تلقائيًا):** كشف 6 أنماط، 3 توصيات، مسودتان جاهزتان، 12 مهمة متأخرة، 5 انتظار متقادم، مطالب مراجعتين قرار.

---

## 2) الشيت تبويبًا تبويبًا — هل يُقرأ؟ أين يُستخدم؟

| # | التبويب (كما في `master-sheet.xlsx`) | الأعمدة | الصفوف | يُستخدم؟ | أين وكيف |
|---|---|---|---|---|---|
| 0 | **اقرأني** | وصف التبويبات | 14 | ⚪ توثيقي فقط | `make_template.py` يولّده، لا يقرأه المحرك منطقيًا |
| 1 | **مهام** | العنوان، النوع، الأولوية، الموعد النهائي، الحالة، السياق/المشروع، المصدر، ملاحظات | **13** | ✅ **نشط 100%** | `chief_of_staff.py`: `top3` (أولويات)، `overdue` (12 متأخرة)، `manager.py` يكشف تأخير، `proactive.py` يبني `open_loops` (i_promised). البريف يعرضها في 🎯 و📉 |
| 2 | **مشاريع** | المشروع، المجال، الحالة، آخر تقدم، الخطوة التالية، الأولوية، تكلفة شهرية، ملاحظات | **11** | ✅ **نشط** | كشف **مشاريع متوقفة فعليًا** (`نشط` + >30يوم بلا تقدم = `كاشف الأنماط KPI` 34يوم)، `manager fast` يولّد `decision_requests` للمشاريع المتوقفة، `proactive` يفتح حلقة `risk`، تُحسب التكلفة `120+40+...` |
| 3 | **عملاء وفرص** | الجهة، الخدمة، المدينة، المصدر، الحالة، آخر تواصل، المتابعة القادمة، القيمة المحتملة، ملاحظات | **8** | ✅ **نشط** | قمع الفرص `funnel`، `pipeline=147,000 ريال`، `no_2nd`=3 بلا تواصل ثانٍ، `due_soon_leads`، مسودات المتابعة `draft_msg` → `action_queue PENDING_APPROVAL` (idempotent ببصمة SHA) |
| 4 | **مؤشرات القسم** | التاريخ، المرضى، الجلسات، عدم حضور، متوسط الانتظار، ذروة الانتظار، الموظفون، حوادث/ملاحظات | **30** | ✅ **نشط (كاشف الأنماط)** | أهم محرك قيمة: يحسب `agg(this_w vs prev_w)`، **ذروة الثلاثاء 19%→22%→28%**، `peak_mode=10–12 (n=...)`، حوادث مسجلة. لا يوجد `Executive_Brief` منفصل هنا — البريف يولّده |
| 5 | **مواعيد** | التاريخ، الوقت، الموضوع، الحضور، الهدف، التحضير المطلوب، حالة التحضير | **4** | ✅ **نشط** | `upcoming` + `prep_missing` (نموذج التقييم ناقص)، `proactive SO-001` (اجتماع <30د) و`SO-002` (<48س) و`SO-006` (تعارض 60د) |
| 6 | **قرارات** | التاريخ، القرار، البدائل، الخيار، النتيجة المتوقعة، تاريخ المراجعة، النتيجة الفعلية، الحالة، التقييم/الدرس | **5** | ✅ **نشط** | `dec_due` (مراجعتان مستحقتان: الجبيل + SOAP)، `dec_running` (قيد التنفيذ)، `decision_quality.py` موجود لكن **غير مستدعى في الحلقة** — المراجعة عبر `chief` فقط |
| 7 | **متابعة مرضى** | الرمز، الحالة السريرية، آخر زيارة، الموعد القادم، يحتاج مراجعة خطة، ملاحظات | **6** | ✅ **نشط** | `fu_review`=4 (P-101/102/104/106)، `fu_late` (فات موعده)، `fu_soon`. **برموز مجهلة فقط P-10x — حوكمة خصوصية مطبقة** |
| 8 | **صندوق الصوت** | التاريخ والوقت، النص، التصنيف، تم التحويل، الوجهة | **4** | ✅ **نشط جزئيًا** | `voice_pending`=1 (فكرة فيديو وضعية الجلوس بانتظار التحويل)، `import_inbox.py` يستورد `data/inbox.csv` لكن **لا يُستدعى تلقائيًا في `manager --loop`** — يحتاج تشغيل يدوي أو ربط تيليجرام |
| 9 | **تعلم** | النوع، العنوان، مرتبط بهدف، الحالة، التاريخ، طُبّق عمليًا | **5** | ✅ **نشط** | `learn_done=2/5`, `learn_applied=3/5`, `due_reviews` من `learning_engine.py` (سقف 2/يوم، جدولة 1/3/7/14/30) تظهر في البريف 📚 |
| 10 | **مالية** | البند، النوع، التكلفة/شهر، تاريخ التجديد، آخر استخدام، ملاحظة | **8** | ✅ **نشط** | `fin_total`, `fin_renew` (خلال 30يوم), `fin_unused` (>30يوم: أداة كتابة #1 50يوم + Perplexity 40يوم), `dups` (أداة كتابة #1/#2 مكرر), `savings` التوفير المحتمل. `proactive SO-004/005` (مالي <3أيام، تجديد <7أيام) |

**النتيجة على مستوى الشيت:** 10/10 تبويبات بيانات مربوطة ومُنتِجة في البريف والمراجعة. لا يوجد تبويب مهمل داخل الشيت نفسه. التبويب الوحيد غير المنطقي هو `اقرأني` (توثيق).

### ماذا عن الشيت الحي على Google؟
إن كان الشيت الحي يحوي تبويبات إضافية مثل:
- `Executive_Brief` (يذكرها README: يُحدَّث عبر `/brief` + `brief_discovery.py` + webhook `google_sheets_webhook.gs`)
- `PUBLISH_QUEUE` (لـ Content Creator / Buffer)
- `life_pulse_content_engine` أو `CONTENT_SHEET_ID`

فهذه **ليست في `master-sheet.xlsx`** وبالتالي **غير مُرحّلة إلى `state.json`** حاليًا. هي تعمل فقط عند ضبط `GOOGLE_SHEETS_WEBHOOK_URL` + `GOOGLE_SHEETS_WEBHOOK_SECRET` و`CONTENT_SHEET_ID`. بدونها تبقى فارغة/غير مستخدمة محليًا. لتدقيقها أحتاج جعل الشيت Public (Anyone with link → Viewer) أو إعطائي `export?format=csv`.

---

## 3) المحرك — ما يُستخدم في الإنتاج وما هو نائم

### ✅ الحلقة الحية (يُنفّذ في كل `manager --loop` أو `chief_of_staff.py`)

| الملف | الدور | الدليل أنه نشط |
|---|---|---|
| `engine/store.py` | **مخزن الحالة الموحد** — الكاتب الوحيد، كتابة ذرّية + إصدارات + نسخ دوّارة + `audit.jsonl` — **C1** | 597 إشارة في الكود، قلب كل شيء |
| `engine/manager.py` | حلقة المدير بدورتين: **سريعة كل 15د** (تطبيع waiting v2، OVERDUE→مسودة، انتهاء صلاحية، قرارات متوقفة) + **كاملة 06:00 Asia/Riyadh** (تستدعي `chief_of_staff.py`) + catch-up + write-on-change | 264 إشارة، مُستدعى من `autostart/*` و`proactive_worker` |
| `engine/chief_of_staff.py` | **Agent 0** — يقرأ الحالة ويولّد البريف الصباحي + المراجعة الأسبوعية + كاشف الأنماط + مسودات المتابعة + طابور الاعتماد | يُستدعى من `manager full_cycle` — أنتج اليوم 26 مهمة |
| `engine/scheduler.py` | **11 وظيفة مجدولة** (06:45/07:30/16:00/20:30 + أحد/ثلاثاء/خميس/جمعة + 28/1/آخر يوم) — كلها تولّد **مسودات PENDING_APPROVAL** فقط | `dispatch_due()` داخل `manager --loop`، `today-actions` يدرج 3 إجراءات فورية (DHS 17SEP + NEEDS_INPUT + تحويل صوتي) |
| `engine/proactive.py` | **الوكيل الاستباقي v1.0** — 8 أوامر دائمة SO-001..008، سجل `open_loops`، مصفوفة استقلالية L0–L4، تسجيل نقاط `أثر×استعجال×ثقة×خطر`، حواجز (ثقة 0.8، سقف 6/يوم، هدوء 22:00–06:30، تراجع `undo`, pause) | `proactive.sweep()` داخل `manager --loop`، 266 إشارة، 22 اختبار |
| `engine/approve.py` | **بوابة الاعتماد C2** — `approve A-001 --hash <sha256>`, صلاحية 48س، idempotency | 135 إشارة، يُستدعى بعد كل مسودة |
| `engine/master_os.py` + `engine/drive_tree.py` | شجرة Drive المعيارية `Abdulrahman_Master_OS` (01–05) + مصفوفة الوكلاء الأربعة | 21/22 إشارة، `drive_tree render/checklist` |
| `engine/mindmap.py` + `engine/audio_digest.py` | خريطة Mermaid + ملخص مسموع 5–7د (QUEUED→DIGESTED→NARRATED عبر `ELEVENLABS_API_KEY` env فقط) | 71/64 إشارة، Friday 16:00 و Daily 20:30 |
| `engine/learning_engine.py` | محرك التدريس التكيفي (ILPC + جدولة متباعدة 1/3/7/14/30) + `outline LP-001` | 16 إشارة، سقف مراجعتين/يوم في البريف |
| `engine/voice_call.py` | معالج المكالمات الواردة (تفريغ→تصنيف→ملخص→StateStore→مسودة) + حمايات حقن | 11 إشارة، `demo A|B|C|D|E` + `ingest call.json`، قسم 📞 في البريف |
| `engine/runtime_clock.py` | الساعة الحقيقية (Asia/Riyadh) — يمنع drift | 5 إشارات، مُصحح crash-loop |
| `connectors/telegram_bot.py` + `telegram_bot_legacy.py` + `super_manager.py` + `model_gateway.py` | بوت تيليجرام (webhook إنتاج، polling محمي `AI_OS_ALLOW_POLLING=1`) + توجيه نماذج + تفويض | ~40 أمر: `/start /help /brief /pending /approve /calendar /tasks /proactive /sweep /delegate /manager ...` |

### ⚠️ موجود لكنه **غير مستدعى في الحلقة الحالية** (يحتاج تفعيل يدوي أو دورة أعلى)

| الملف | لماذا هو نائم | ماذا يلزم لتفعيله |
|---|---|---|
| `engine/v05_cycle.py` → `v06_cycle.py` → `v07_cycle.py` → `v08_cycle.py` | سلسلة دورات تراكمية (v05: rag+observability+control_center، v06: reflection+self_review، v07: change+governance+backup+trust، v08: live_sync+v07) — **لا أحد يستدعيها**؛ `manager --loop` يستدعي المكونات مباشرة | تشغيل يدوي: `python3 engine/v07_cycle.py` أو ربطها في `manager --loop` / CI |
| `engine/import_inbox.py` + `engine/migrate.py` + `engine/make_template.py` | أدوات لمرة واحدة: استيراد `inbox.csv` → الحالة، ترحيل الشيت → الحالة، بناء قالب الشيت | تُشغَّل يدويًا: `python3 engine/migrate.py --force` / `import_inbox.py` / `make_template.py` — ليست في الـloop |
| `engine/rag.py` + `engine/search.py` + `engine/context_service.py` | RAG وبناء الفهرس والبحث الدلالي — يُبنى عبر `v05_cycle` فقط | `python3 engine/rag.py build` |
| `engine/reflection_engine.py` + `engine/self_review.py` + `engine/skill_*` (5 ملفات) + `engine/skill_runtime.py` | منظومة المهارات الإجرائية (Experience→Lesson→Candidate→Testing→Approval→Active) — **صفر مهارات مولّدة**، `skills/generated/` فارغ، `skill_runtime` **0 إشارة** في كل الكود | تحتاج `reflection` دوري + `skill_admin approve/activate` — حاليًا تصميم فقط |
| `engine/change_intelligence.py` + `engine/source_governance.py` + `engine/decision_quality.py` + `engine/observability.py` + `engine/trust_dashboard.py` + `engine/backup_verify.py` | طبقة الثقة v0.7 — كشف تغييرات، حوكمة مصادر، مراجعة قرارات 30يوم، لوحة ثقة | تُستدعى فقط من `v07_cycle` — غير مفعلة |
| `engine/energy_log.py` + `engine/okr.py` + `engine/behavior_model.py` + `engine/memory.py` | سجل الطاقة، OKRs، نموذج سلوك، ذاكرة طبقية — **مُهيكلة لكن فارغة** (`okrs=0`, `energy_log=0` في `state.json`) | تحتاج إدخال بيانات: `python3 engine/energy_log.py 7 3 --note ...` / تعبئة OKRs |
| `engine/live_sync.py` + `engine/import_drive.py` | مزامنة مصادر حية (Drive/Sheets) قراءة فقط | تحتاج `GOOGLE_*` env + تشغيل `v08_cycle` |
| `engine/control_center.py` + `engine/render_html.py` + `engine/render_approvals.py` + `engine/export_for_chat.py` | توليد HTML/لوحات/تصدير سياق للـLLM — تُستدعى ضمنيًا من `chief_of_staff` لكن ليست نقاط دخول مستقلة في الحلقة | تعمل ضمن `chief`، لا حاجة لتفعيل |
| `engine/persistence_nudge.py` + `engine/social_triage.py` + `engine/previsit_intelligence.py` + `engine/telegram_smoke_test.py` | أدوات صغيرة/تجريبية — **0–2 إشارة** فقط | مهملة — يمكن أرشفتها |
| `connectors/*` غير المفعلة (14) | `action_language_safety`, `aws_transcribe`, `bridge_api`, `brief_runtime`, `capability_runtime`, `commerce_checkout`, `commerce_scout`, `github_live`, `google_workspace`, `telegram_live`, `multi_intent_runtime`, `content_runtime` … | Stubs لمستقبل (Commerce/Buffer/Calendar) — لها اختبارات لكن لا تُستدعى في webhook الحالي |

### ❌ مُؤرشف / لا يُنشر

| المسار | الحالة | الإجراء |
|---|---|---|
| `portfolio/` | **مؤرشف** — النسخة القانونية الآن في `addn2030-svg/abdulrahman-portfolio` (منفصل public) | لا تنشره من هذا المستودع — workflow الصفحات محذوف عمدًا |
| `.github/workflows/buffer-publish.yml` + `strategic-shadow-dev.yml` | Workflows قديمة | النشط فقط `production-model-router.yml` |
| `knowledge/` (4 ملفات) | مرجع صوتي/سياقي — يُستخدم عبر `rag`/`context_service` فقط (غير مفعل حاليًا) | يُفعّل مع `rag build` |
| `prompts/` (15 حزمة) | 8 منها **0 إشارة** في الكود: `decision-twin`, `clinical-intelligence`, `meeting-to-execution`, `master-os-agents`, `proactive-chief-of-staff`, `voice-relationship`, `voice-to-action` | حزم للصق يدوي في ChatGPT/Claude — ليست تكاملًا برمجيًا |

---

## 4) ماذا يُحسب اليوم فعليًا من الشيت (أرقام حية 15SEP2026)

بعد `migrate --force` + `chief_of_staff.py`:

- **البريف:** `reports/daily-brief-2026-09-15.md` — باب اليوم **العلاج الطبيعي العميق**، 3 أولويات متأخرة 28/23/23 يوم، مراجعتان قرار مستحقتان، 4 مرضى يحتاجون مراجعة خطة، 5 انتظار متقادم (33–45 يوم)، خطر **الثلاثاء 28%**، فرصة **MSD شركات 147,000 ريال**
- **المراجعة:** `reports/weekly-review-2026-W33.md` — مقارنة هذا الأسبوع (16–20 أغسطس) بالسابق، 6 أنماط، 3 توصيات نهائية فقط (قاعدة 50→3)
- **اللوحة:** `reports/dashboard-latest.html` + `approvals-latest.html` (مسودتان `PENDING_APPROVAL` ببصمة SHA، تنتهي بعد 48س)
- **الحالة:** `data/state.json` v1 — 94 صف + 5 انتظار + 0 voice_calls + 0 decision_requests (قبل `manager fast` الذي سيولّدها)

**ما لم يُحسب لأنه فارغ:** `okrs=0`, `energy_log=0`, `learning_reviews=0`, `finance_ebsi=0`, `unified_inbox=0`, `drive_tree=0` — كلها أقسام مهيأة في `store.py` لكن بلا بيانات.

---

## 5) التوصيات — ماذا تفعل الآن

### للشيت الحي (الرابط الذي أرسلته)
1. اجعله **Anyone with link → Viewer** مؤقتًا أو شاركه مع Service Account، ثم أعد إرسال الرابط — سأعيد التدقيق المباشر على تبويبات `Executive_Brief` / `PUBLISH_QUEUE` إن وجدت، وأقارنها بالـ11 تبويب أعلاه.
2. إن كان الشيت الحي يحوي `Executive_Brief` فهو **يُستخدم** عبر `brief_discovery.py` + `google_sheets_webhook.gs` (يتطلب `GOOGLE_SHEETS_WEBHOOK_URL`). إن لم يكن موجودًا فلا شيء ناقص.

### لتنظيف المستودع (اختياري — يقلل الضوضاء)
- **أرشفة/حذف المقترح:** `persistence_nudge.py`, `skill_runtime.py`, `social_triage.py`, `telegram_smoke_test.py`, `v08_cycle.py` (0 إشارة) — أو انقلها إلى `engine/archive/`.
- **تفعيل أو توثيق:** إما فعّل `v07_cycle` في `manager --loop` (للحصول على `change_intelligence` + `trust_dashboard`) أو وثّق أنها **معطلة عمدًا حتى اكتمال Trust Layer**.

### لتفعيل الميزات النائمة (حسب الأولوية)
1. **صندوق الصوت الحي:** اربط `tools/daily-inbox.html` → `data/inbox.csv` → `import_inbox.py` في `autostart` أو webhook تيليجرام صوتي (ar-SA).
2. **OKRs والطاقة:** ابدأ بإدخال `energy_log` يوميًا و`okrs` ربع سنوي — ستظهر تلقائيًا في المراجعة الأسبوعية.
3. **RAG والمعرفة:** `python3 engine/rag.py build` بعد وضع كتبك في `knowledge/` وDrive المهيكل `Abdulrahman_Master_OS`.
4. **المهارات:** شغّل `python3 engine/reflection_engine.py reflect` أسبوعيًا — إن لم تردها، احذف `skills/*` لتقليل الالتباس.

---

## 6) جدول سريع: مستخدم ✅ vs غير مستخدم ❌ (للمشاركة)

| الفئة | مستخدم ✅ | غير مستخدم ❌ / نائم 💤 |
|---|---|---|
| **الشيت (11 تبويب)** | مهام، مشاريع، عملاء، مؤشرات، مواعيد، قرارات، متابعة مرضى، صندوق صوت، تعلم، مالية (10/10) | اقرأني (توثيقي) |
| **الحلقة الإنتاجية** | store, manager, chief, scheduler (11 job), proactive (8 SO), approve | v05–v08_cycles, import_inbox, migrate, make_template (مرة واحدة) |
| **المعرفة والصوت** | mindmap, audio_digest, master_os, drive_tree, learning_engine, voice_call | rag, search, context_service, live_sync, import_drive (تحتاج تفعيل) |
| **الثقة والتحسين** | — (لا شيء منها في الحلقة) | change_intelligence, source_governance, decision_quality, observability, trust_dashboard, reflection, self_review, backup_verify |
| **المهارات** | — | 6 ملفات skill_* + skill_runtime (0 مهارات ACTIVE) |
| **تيليجرام** | telegram_bot, telegram_bot_legacy, super_manager, model_gateway, bedrock_team, ops_context, content_creator, commerce_agent … | 14 connector stub (aws_transcribe, github_live …) |
| **الواجهات** | daily-brief, weekly-review, dashboard, approvals-latest.html | control_center standalone, export_for_chat, portfolio (مؤرشف) |

---

**الخلاصة للمشارك:** الشيت **مُستغل بالكامل** — لا يوجد تبويب بيانات مهمل. الهدر الوحيد هو **كود موجود لا يُنفّذ في الإنتاج** (طبقات v0.5–v0.8 والمهارات). إما فعّلها بقرار واضح أو أرشفها لتخفيف التعقيد.

> تريد تدقيقًا مباشرًا على الشيت الحي؟ اجعله Public مؤقتًا وأعد إرسال الرابط — أو حمّل `File → Download → Microsoft Excel` وأرفقه هنا وسأقارنه حرفيًا بالـmaster-sheet.xlsx.

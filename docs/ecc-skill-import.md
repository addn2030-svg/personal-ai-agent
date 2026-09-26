# استيراد مهارات ECC — كتالوج خارجي تحت بوابتنا

## المشكلة

مستودع [`affaan-m/ecc`](https://github.com/affaan-m/ecc) يحمل **292 مهارة** جاهزة
(هندسة وكلاء، حلقات تعلّم، ميزانية سياق، تقييم…). إغراء النسخ واللصق كبير، والخطأ
الذي يليه معروف: نص كتبه غريب يدخل سياق وكيل شخصي بلا مراجعة، فيتحول «مورد مفيد»
إلى تعليمات غير موقَّعة تنفّذ باسم المالك.

القاعدة هنا: **المصدر الخارجي لا يمنح ثقة.** الكتالوج يدخل من الباب نفسه الذي تدخل
منه المهارة المولّدة ذاتيًا — `CANDIDATE → TESTING → APPROVED → ACTIVE` — بلا اختصار.

## ما يفعله `engine/skill_import.py`

يمسح `vendor/ecc/skills/*/SKILL.md`، يصنّف كل مهارة، يفحصها، ثم يسجّلها في
`skill_registry` كمرشّح **بمصدرٍ موثّق**. لا يفعّل شيئًا ولا يلمس مهارة قائمة.

### 1) التصنيف يعتمد على الاسم لا على الوصف

الوصف نثر تسويقي يوقع في تطابقات كاذبة: مهارة `agent-introspection-debugging`
وصفها يذكر «diagnostics» فتُصنَّف **سريرية** — وتلويث النطاق السريري في وكيل صحي
شخصي خطأ لا يُحتمل. لذلك التصنيف يقرأ **رموز الـslug** أولًا، والوصف لا يُستشار إلا
بعبارات ضيقة لا تحتمل التأويل (`patient data`, `private key`, `deploy to production`).

| الرموز | النطاق | الطبقة |
|---|---|---|
| `healthcare`, `clinical`, `patient`, `hipaa` | `clinical` | 🔒 locked |
| `security`, `auth`, `secret`, `vulnerability`, `crypto` | `security` | 🔒 locked |
| `rbac`, `permission`, `iam` | `permissions` | 🔒 locked |
| `deploy`, `payment`, `kubernetes`, `shell`, `migration`, `e2e` | `external_execution` | 🔒 locked |
| `writing`, `content`, `brand`, `docs`, `slides` | `communications` | 👤 review |
| `pricing`, `invoice`, `revenue` | `finance` | 👤 review |
| ما تبقّى | `projects` | 👤 review |

**لا شيء يصل إلى طبقة `low` إطلاقًا.** الطبقة المتساهلة (التي تسمح بالتفعيل التلقائي
بعد 90% نجاح) مخصّصة لما ولّده النظام من تجربة المالك — لا لنص مستورد. الاستيراد
يتحقق من ذلك وقت التنفيذ ويرفع `AssertionError` لو انزلق التصنيف يومًا.

التوزيع الحالي: **263 مراجعة · 29 مقفلة**.

### 2) ثلاثة حواجز قبل الكتابة

- **فحص أسرار**: مفاتيح AWS/OpenAI/GitHub/Slack، توكن بوت تيليجرام، مفاتيح خاصة،
  واعتمادات مكتوبة سطريًا. أي إصابة ⇒ **رفض** المهارة كاملة (لا تنقيح صامت).
- **وصف إلزامي**: مهارة بلا `description` في الـfrontmatter مجهولة الغرض ⇒ رفض.
- **ميزانية السياق**: جسم > 20,000 حرف يُرفض؛ `skill_runtime.context_for` سقفه 6,000
  حرف، فمهارة بـ30 ألف حرف لن تُحمَّل أبدًا وستشغل السجل بلا فائدة. (22 مهارة مرفوضة لهذا السبب.)

### 3) المصدر موثّق والتكرار مستحيل

كل سجل يحمل `source` فيه `system` و`slug` و`sha256` للجسم و`path` والرخصة، و`evidence_ids`
تحمل `ECC:<slug>@<hash12>`. إعادة الاستيراد بالبصمة نفسها ⇒ `unchanged` (لا صف مكرر).
تغيّر النص في المنبع ⇒ **نسخة جديدة** `v2` بمسار الاعتماد نفسه — لا كتابة فوق نسخة
قيد المراجعة. و`drift` يكشف ما تغيّر أعلى المجرى دون استيراد.

### 4) `annotate` لا يرقّي

أُضيفت `skill_registry.annotate()` لتسجيل المصدر. حقولها المحمية
(`status`, `risk_tier`, `domain`, `version`, `file`, `metrics`, `id`, `slug`) مرفوضة
بـ`PermissionError` — فلا يصبح تسجيل بيانات وصفية بابًا خلفيًا للترقية. الترقية تبقى
في `set_status` وحدها.

## الاستخدام

```bash
# 1) إحضار المصدر (خارج git — vendor/ متجاهَل)
git clone --depth 1 https://github.com/affaan-m/ecc.git vendor/ecc

# 2) استعراض الكتالوج وتصنيفه (لا يكتب شيئًا)
python3 engine/skill_import.py scan
python3 engine/skill_import.py scan --filter eval

# 3) خطة الاستيراد: الجديد · المحدَّث · المرفوض وسببه (لا يكتب شيئًا)
python3 engine/skill_import.py plan
python3 engine/skill_import.py plan --filter agent --limit 20

# 4) التنفيذ — ينشئ CANDIDATE فقط
python3 engine/skill_import.py import --slug context-budget,eval-harness
python3 engine/skill_import.py import --filter memory

# 5) المتابعة
python3 engine/skill_import.py status   # ما استُورد وحالته
python3 engine/skill_import.py drift    # ما تغيّر في المنبع
```

مسار المصدر يُضبط بـ`ECC_SKILLS_DIR` إن كان الاستنساخ في مكان آخر.

## بعد الاستيراد — مسار الاعتماد لا يتغير

```bash
python3 engine/skill_registry.py list           # المرشّحون
python3 engine/skill_evaluator.py SK-XXXX       # اختبار الانحدار
python3 engine/skill_admin.py approve SK-XXXX   # اعتماد بشري
python3 engine/skill_admin.py activate SK-XXXX  # تفعيل (يتقاعد الإصدار السابق)
```

قبل `ACTIVE` لا تظهر المهارة في `skill_runtime.context_for()` — أي أنها **لا تدخل
سياق النموذج ولو كانت مسجّلة**. والمقفلة (`clinical`/`security`/`permissions`/
`external_execution`) لا تُفعَّل تلقائيًا في أي حال.

## الدفعة الأولى المستوردة (10 مرشّحين)

اختيرت لصلتها المباشرة بمحرّك هذا النظام لا لكثرتها:
`context-budget` · `unified-memory` · `iterative-retrieval` · `continuous-learning-v2` ·
`agent-self-evaluation` · `eval-harness` · `verification-loop` · `operator-approval-loop` ·
`prompt-optimizer` · `deep-research`.

كلها `projects/review/CANDIDATE`. البقية (260 مؤهلة) على بعد أمر واحد متى لزمت.

## الاختبارات

`tests/test_skill_import.py` — 29 اختبارًا تغطي: تحليل الـfrontmatter · التصنيف
والتطابقات الكاذبة · منع طبقة `low` · فحص الأسرار · حدّ الحجم · المصدر والبصمة ·
اللاتكرار · النسخة الجديدة عند تغيّر المنبع · أن المرشّح **لا يُحمَّل** في السياق ·
أن التفعيل بلا اعتماد يرفع `PermissionError` · أن المسار الشرعي (approve→activate)
ما زال يعمل · أن `annotate` لا تمسّ الحقول المحمية.

```bash
python3 -m unittest tests.test_skill_import
```

## ما لم يُستورد عمدًا

`agents/` (68) و`commands/` (94) و`hooks/` في ECC مبنية على أدوات harness خارجية
(Claude Code · Codex · Cursor) لا على محرّك هذا المستودع. استيرادها اليوم يعني نسخ
واجهة لا تنفّذ. المهارات وحدها نص إجرائي محايد — وهي ما استُورد.

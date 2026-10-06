# استيراد مهارات خارجية — كتالوج غريب تحت بوابتنا

## المشكلة

مستودعات المهارات الجاهزة صارت وفيرة: [`affaan-m/ecc`](https://github.com/affaan-m/ecc)
فيه **292 مهارة**، و[`nextlevelbuilder/ui-ux-pro-max-skill`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
فيه **7**. إغراء النسخ واللصق كبير، والخطأ الذي يليه معروف: نص كتبه غريب يدخل سياق
وكيل شخصي بلا مراجعة، فيتحول «مورد مفيد» إلى تعليمات غير موقَّعة تنفّذ باسم المالك.

القاعدة هنا: **المصدر الخارجي لا يمنح ثقة.** الكتالوج يدخل من الباب نفسه الذي تدخل
منه المهارة المولّدة ذاتيًا — `CANDIDATE → TESTING → APPROVED → ACTIVE` — بلا اختصار.

## ما يفعله `engine/skill_import.py`

يمسح `<الجذر>/<slug>/SKILL.md`، يصنّف كل مهارة، يفحصها، ثم يسجّلها في `skill_registry`
كمرشّح **بمصدرٍ موثّق**. لا يفعّل شيئًا ولا يلمس مهارة قائمة.

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

### 2) مهارة تشحن كودًا تُصعَّد إلى `locked`

نستورد `SKILL.md` **وحده**. لكن كثيرًا من المهارات تشحن معها `scripts/*.py` أو
`*.sh` أو `*.cjs`، ونصّها يقول «شغّل `scripts/logo/search.py`». النتيجة لو مررناها
كنص عادي: مهارة تبدو إجرائية بريئة بينما غرضها الحقيقي **تنفيذ كود**، وإحالاتها
مكسورة أصلًا لأن الكود لم يُنقل.

القاعدة: وجود ملف تنفيذي في مجلد المهارة ⇒ النطاق `external_execution` والطبقة
`locked` **مهما قال الاسم أو الوصف**. ويُسجَّل في المصدر عدد ما لم يُستورد
(`not_imported.executables` و`not_imported.companions`) كي يرى المراجع الصورة كاملة.

> هذه القاعدة صحّحت خطأً وقع في الاستيراد الأول: `agent-self-evaluation` و
> `continuous-learning-v2` و`operator-approval-loop` من ECC صُنّفت `review` لأن الماسح
> لم ينظر أبعد من `SKILL.md` — وهي تشحن `evaluate.py` و`observer-loop.sh` و
> `approval_claims.py`. صارت الآن `locked`.

### 3) ثلاثة حواجز قبل الكتابة + تحذير صريح

- **فحص أسرار**: مفاتيح AWS/OpenAI/GitHub/Slack، توكن بوت تيليجرام، مفاتيح خاصة،
  واعتمادات مكتوبة سطريًا. أي إصابة ⇒ **رفض** المهارة كاملة (لا تنقيح صامت).
- **وصف إلزامي**: مهارة بلا `description` في الـfrontmatter مجهولة الغرض ⇒ رفض.
- **حدّ 20,000 حرف**: ما تجاوزه يُرفض.
- **تحذير سقف التحميل**: `skill_runtime.context_for` سقفه **6,000** حرف، فمهارة
  بـ13 ألف حرف ستُسجَّل ولن تُحمَّل أبدًا بالإعداد الحالي. لا نمنعها (قد يرفع المالك
  السقف) لكن **نقولها صراحةً** في `scan`/`plan`/`import` وفي سجل المصدر — لا قبول
  صامت ولا رفض صامت.

### 4) المصدر موثّق، والتصادم بين المصادر مستحيل

كل سجل يحمل `source` فيه `system` و`slug` و`sha256` للجسم و`path` والرخصة.
مفتاح التتبع **مركّب `(system, slug)`**، والـslug في السجل مسبوق باسم المصدر
(`ecc-design-system` مقابل `uiux-design-system`) — لأن `design-system` موجود في
المستودعين ولا علاقة بينهما، والمفتاح بالـslug وحده كان سيجعل أحدهما يبدو «نسخة
ثانية» من الآخر فيرث تاريخ اعتماد لا يخصه.

إعادة الاستيراد بالبصمة نفسها ⇒ `unchanged`. تغيّر النص في المنبع ⇒ **نسخة جديدة**
بمسار الاعتماد نفسه — لا كتابة فوق نسخة قيد المراجعة. و`drift` يكشف المتغيّر دون استيراد.

### 5) `annotate` لا يرقّي

أُضيفت `skill_registry.annotate()` لتسجيل المصدر. حقولها المحمية
(`status`, `risk_tier`, `domain`, `version`, `file`, `metrics`, `id`, `slug`) مرفوضة
بـ`PermissionError` — فلا يصبح تسجيل بيانات وصفية بابًا خلفيًا للترقية. الترقية تبقى
في `set_status` وحدها.

## الاستخدام

```bash
# 1) إحضار المصدر (خارج git — vendor/ متجاهَل)
git clone --depth 1 https://github.com/affaan-m/ecc.git vendor/ecc
git clone --depth 1 https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git vendor/ui-ux-pro-max

# 2) استعراض الكتالوج وتصنيفه (لا يكتب شيئًا)
python3 engine/skill_import.py scan --dir vendor/ecc/skills --source ecc
python3 engine/skill_import.py scan --dir vendor/ui-ux-pro-max/.claude/skills --source uiux

# 3) خطة الاستيراد: الجديد · المحدَّث · المرفوض وسببه (لا يكتب شيئًا)
python3 engine/skill_import.py plan --dir vendor/ecc/skills --source ecc --filter agent

# 4) التنفيذ — ينشئ CANDIDATE فقط
python3 engine/skill_import.py import --dir vendor/ecc/skills --source ecc \
  --license "MIT (affaan-m/ecc)" --slug context-budget,eval-harness

# 5) المتابعة
python3 engine/skill_import.py status                       # ما استُورد وحالته
python3 engine/skill_import.py drift --dir ... --source ...  # ما تغيّر في المنبع
```

الأعلام: `--dir` (جذر المهارات) · `--source` (اسم المصدر في السجل) · `--license` ·
`--slug a,b` · `--filter نص` · `--limit N`. وبلا `--dir` يُقرأ `ECC_SKILLS_DIR` ثم
`vendor/ecc/skills`. وغياب المجلد ليس خطأً — خرج نظيف بلا استثناء.

## بعد الاستيراد — مسار الاعتماد لا يتغير

```bash
python3 engine/skill_admin.py pending           # المرشّحون
python3 engine/skill_evaluator.py SK-XXXX       # اختبار الانحدار
python3 engine/skill_admin.py approve SK-XXXX   # اعتماد بشري
python3 engine/skill_admin.py activate SK-XXXX  # تفعيل (يتقاعد الإصدار السابق)
```

قبل `ACTIVE` لا تظهر المهارة في `skill_runtime.context_for()` — أي أنها **لا تدخل
سياق النموذج ولو كانت مسجّلة**. والمقفلة لا تُفعَّل تلقائيًا في أي حال.

## المستورد حاليًا (17 مرشّحًا)

**ECC — 10** (اختيرت لصلتها بمحرّك هذا النظام لا لكثرتها):
`context-budget` · `unified-memory` · `iterative-retrieval` · `deep-research` ·
`eval-harness` · `verification-loop` · `prompt-optimizer` — طبقة `review`؛
و`agent-self-evaluation` · `continuous-learning-v2` · `operator-approval-loop` —
**`locked`** لشحنها سكربتات. البقية (260 مؤهلة) على بعد أمر واحد.

**ui-ux-pro-max — 7** (الكتالوج كاملًا):
`banner-design` · `slides` — طبقة `review`؛
و`brand` · `design` · `design-system` · `ui-styling` · `ui-ux-pro-max` —
**`locked`** (تشحن 46 ملفًا تنفيذيًا مجتمعةً).

### تنبيه على ui-ux-pro-max تحديدًا

هذا المستودع **ليس نصًا إجرائيًا** في جوهره: هو إضافة Claude Code فيها قاعدة بيانات
محلية قابلة للبحث (79 نمطًا · 192 لوحة ألوان · 74 اقتران خطوط) وسكربتات بايثون/Node
تُستدعى من نص المهارة. ما استوردناه هو **النص وحده**، ونصوص 5 من 7 تحيل إلى سكربتات
لم تُنقل. لذلك:

- الفائدة الفعلية من الاستيراد: التوجيه والقواعد والمعايير المكتوبة (مفيدة كسياق).
- ما لا يعمل: أي خطوة تقول «شغّل `scripts/...`» — وهذا سبب تصعيدها إلى `locked`.
- لو أردت قدراته التنفيذية فعلًا، فمحلّه **أداة موصولة** (`connectors/`) أو استخدامه
  في محرّره الأصلي، لا مهارة في الذاكرة الإجرائية. الاستيراد هنا لا يدّعي غير ذلك.

## الاختبارات

`tests/test_skill_import.py` — **38 اختبارًا** تغطي: تحليل الـfrontmatter · التصنيف
والتطابقات الكاذبة · منع طبقة `low` · التصعيد عند شحن الكود · فصل المصادر المتصادمة ·
فحص الأسرار · حدّ الحجم وتحذير سقف التحميل · المصدر والبصمة · اللاتكرار · النسخة
الجديدة عند تغيّر المنبع · أن المرشّح **لا يُحمَّل** في السياق · أن التفعيل بلا اعتماد
يرفع `PermissionError` · أن المسار الشرعي (approve→activate) ما زال يعمل · أن
`annotate` لا تمسّ الحقول المحمية.

```bash
python3 -m unittest tests.test_skill_import
```

## ما لم يُستورد عمدًا

`agents/` (68) و`commands/` (94) و`hooks/` في ECC مبنية على أدوات harness خارجية
(Claude Code · Codex · Cursor) لا على محرّك هذا المستودع. استيرادها اليوم يعني نسخ
واجهة لا تنفّذ. وكذلك سكربتات ui-ux-pro-max ومراجعها وقواعد بياناتها (CSV) —
تبقى في `vendor/` خارج git.

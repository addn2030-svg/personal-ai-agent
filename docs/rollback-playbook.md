# دليل التراجع — Rollback Playbook (نسخة تشغيلية)

**متى تستخدم أي مسار** — القاعدة: كوميت على main = نشر حي عندك مباشرة (Railway ينشر من main).

## 1. تراجع كود فقط (الخدمة تعمل لكن السلوك خطأ)

الحالة: كوميت أفسد سلوكًا، لكن الخدمة تقاوم ولا يوجد فقدان بيانات.

```bash
# (أ) اعكس الكوميت المسبب — الأنظف والأدق:
git revert --no-edit <SHA>
git push origin main          # ← Railway ينشر المعكوس تلقائيًا

# (ب) أو ارجع للنسخة السابمة بالقوة (يمسح كل ما بينهما — استخدمه فقط إن كانت عدة كوميتات سيئة):
git revert --no-commit HEAD~3..HEAD   # يعكس آخر 3 كوميتات
git commit -m "revert: rollback to <SHA>"
git push origin main
```

## 2. كود + بيانات (الكوميت أفسد الحالة)

الحالة: كوميت حوّل/كتب `state.json` خطأً (مثلًا حذف مهام).

```bash
git revert --no-edit <SHA> && git push origin main
# ثم استعد آخر نسخة سليمة من Supabase:
python3 -m connectors.supabase_state list                 # شاهد النسخ
python3 -m connectors.supabase_state restore --id <N>    # معاينة بلا كتابة
python3 -m connectors.supabase_state restore --id <N> --apply   # كتابة فعلية
```

ملاحظة: `ensure_boot_state()` (morning_brief) يستعيد تلقائيًا إن كان `state.json` تالفًا —
لن تحتاج هذه الخطوة إلا لو أفسد الكوميت بيانات **سليمة البنية** (أخطر حالة — راجع النسخ يدويًا).

## 3. الحالة الحرجة — الرجوع لنشر سابق فورًا (بلا كود)

الحالة: الخدمة crash-loop أو توقف تام ولا وقت لانعكاس كوميت.

1. Railway → **Deployments** ← آخر نشر **SUCCESS** سابق ← قائمة ⋯ ← **Redeploy**.
2. يعود البوت للنسخة الأخيرة العاملة خلال دقيقة واحدة (نفس image قديمة، بلا بناء).
3. **لا توقف النشر التلقائي** — كوميت المعكوس بعدها بهدوء كما في (1).

## 4. كارثة بيانات كاملة (فُقد الـ volume)

الحالة: `state.json` مفقود/تالف.

- الأمان تلقائي: عند الإقلاع `ensure_boot_state()` يستعيد أحدث نسخة من Supabase
  (`SUPABASE_RESTORE_ON_BOOT` الافتراضي 1). راقب سجل الخدمة لسطر:
  `boot-safety: state.json مفقود/تالف — استعادة أحدث نسخة`
- يدويًا: مثل (2) — `restore --id <N> --apply`.

## قواعد عامة (لا تُخالفها)

- لا `git push --force` إلى main أبدًا (يسبب انقسام ويفقد كوميتات الآخرين/Copilot).
- لا تراجع كوميت بيانات (Supabase migration) بلا قراءة الـ diff أولًا —
  التراجع عن `drop table` غير ممكن إن لم تكن هناك نسخة.
- بعد أي تراجع: أرسل رسالة اختبار للبوت (`/diag`) وأكّد عودة `boot-safety` سليمًا.
- إذا رجعت للوراء بـ Redeploy، **سجّل** السبب في `docs/decision-*.md` قبل الكوميت المعكوس.

## أسماء الأوامر في مكانها (بحثك السريع)

| تريد | الأمر |
|---|---|
| رؤية النسخ | `python3 -m connectors.supabase_state list` |
| معاينة استعادة | `... restore --id N` (بلا `--apply`) |
| استعادة فعلية | `... restore --id N --apply` |
| عكس كوميت | `git revert --no-edit SHA && git push` |
| رجوع فوري | Railway → Deployments → Redeploy |
# تطوير الكود — التنسيق الموحد عبر الأدوات
## Copilot في GitHub · فروع arena · Railway

**القاعدة الأساس:** أي أداة تعمل على نفس المستودع `addn2030-svg/personal-ai-agent`.
كل تطوير يمر بنفس المسار الثابت:

```
فرع قصير ← مراجعة (diff صغير) ← merge إلى main ← Railway deploy ← تحقق حي
```

---

## 1) تسمية الفروع (كل الأدوات)

| البادئة | الاستخدام | مثال |
|---|---|---|
| `fix/` | إصلاح خلل | `fix/telegram-asterisk-sanitizer` |
| `feat/` | ميزة جديدة | `feat/supabase-intake-logging` |
| `docs/` | توثيق فقط | `docs/cutover-plan-2026-11-11` |
| `chore/` | صيانة/إعداد | `chore/env-vars-cleanup` |

- فروع Copilot في GitHub تبدأ بـ `copilot/` (يضيفها تلقائيًا).
- فروع arena القديمة (`arena/01a...`) **مقفلة تاريخيًا — لا تُدمج**. أي عمل arena جديد يبدأ من main ببادئة `fix/` أو `feat/`.

## 2) رسائل الالتزام (commit messages)

صيغة موحدة واحدة:
```
نطاق: وصف قصير بالعربية أو الإنجليزية — تفصيل إن وُجد
```
أمثلة حقيقية من هذا المستودع:
- `telegram: strip bold/italic markers from bot replies`
- `supabase: 03 operational mirrors from task-plan workbook`
- `docs: approved architectural decision — Supabase cutover`

## 3) مسار Copilot في GitHub

1. افتح المستودع → تبويب **Copilot** أو أنشئ Issue بوصف المطلوب.
2. اطلب التغيير → ينشئ Copilot فرعًا + **Pull Request** تلقائيًا.
3. **لا تضغط Merge قبل:** قراءة diff الملفات المتغيرة، ومراجعة وجودة
   أسماء المتغيرات وعدم حذف أي شيء خارج النطاق.
4. بعد الدمج: تتحقق أن Railway التقط النشر (auto-deploy من main)،
   ثم ترسل رسالة اختبار للبوت.

## 4) مسار فروع arena

أي عمل arena جديد: يبدأ من `main`، اسمه `fix/...` أو `feat/...`،
بحد أقصى **5 ملفات و~200 سطر** لكل فرع — صغيرة بما يكفي للمراجعة في دقيقتين.
لا تُبنى فوق فروع arena قديمة أبدًا.

## 5) مسار Railway

- Railway ينشر من `main` تلقائيًا. **كل merge = نشر.**
- قبل أي نشر كبير: تأكد من أمر التراجع — تبويب Deployments →
  النشر السابق → **Redeploy** (رجوع فوري للنسخة السابقة).
- المتغيرات الحساسة لا تدخل الكود أبدًا — فقط Railway Variables
  والـ `.env` المحلي (مستثنى من Git أصلًا).

## 6) قائمة تحقق قبل الدمج (كل فرع، كل أداة)

- [ ] `python -m py_compile` على كل ملف .py متغير
- [ ] لا أسرار (مفاتيح/كلمات) في الكود
- [ ] لا حذف خارج نطاق المطلوب
- [ ] رسالة الالتزام بالصيغة الموحدة أعلاه
- [ ] بعد الدمج: تحقق من نشر Railway + رسالة اختبار للبوت

آخر تحديث: 2026-11-02
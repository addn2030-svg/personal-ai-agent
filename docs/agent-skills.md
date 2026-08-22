# 🧠 جرد مهارات الوكيل المدير الشخصي — Abdulrahman AI OS v0.4.x
> الطبقتان: **مهارات لغوية** (11 حزمة أوامر — العقل) + **مهارات حتمية** (9 محركات — الأرقام والقواعد). التوجيه: طلبك يحدد المهارة، لا العكس.

## أ) المصفوفة الكاملة — تغطية حياتك

| حياتك | مهارة الوكيل | الحزمة/المحرك | الحالة |
|---|---|---|---|
| الإدارة التنفيذية | Chief of Staff | `chief-of-staff.md` + المحرك | ✅ كاملة |
| الصوت ← قرارات | Voice → Action | `voice-to-action.md` + `import_inbox` | ✅ كاملة |
| المكالمات الواردة | Voice Relationship | `voice-relationship.md` + `voice_call.py` | ✅ (الربط الحي مرحلة 2) |
| القرارات | Decision Twin | `decision-twin.md` + `manager.py` (طلبات قرار) | ✅ كاملة |
| الاجتماعات | Meeting → Execution | `meeting-to-execution.md` | ✅ كاملة |
| التفاوض | Negotiation | `negotiation.md` (مبني على تجربتك الفعلية) | ✅ جديدة |
| السريري | Clinical Intelligence | `clinical-intelligence.md` (IMTAF/NKT/RedFlags) | ✅ كاملة |
| التدريس والتعلّم | Personal Training (ILPC) | `personal-training.md` + `learning_engine.py` | ✅ الأقوى — خريطة إتقان وسلم متباعد |
| الكتابة الأكاديمية | Writer | `writer.md` | ✅ جديدة |
| الرحلات | Travel | `travel.md` (بطاقة رحلة لكل سفريك القادمين) | ✅ جديدة |
| الأسرة والأبناء | Family Guardian | `family.md` (يحمي ولا يكلف) | ✅ جديدة |
| تشغيل القسم | Rehab Operations | محرك KPI + كاشف الأنماط (الثلاثاء!) | ✅ كاملة |
| الأعمال والعملاء | Business & Leads | محرك القمع + الفرص | ✅ (التسويق الاستراتيجي مرحلة 2) |
| المال | Finance | محرك الاشتراكات/التوفير + خط أساس دخلك | ✅ (التسعير وتكلفة الخدمة مرحلة 2) |
| المعرفة والذاكرة | Knowledge & Registry | سجل الأصول (65+) + المصادر | ✅ (RAG المستندات مرحلة 2) |
| الأمان والحوكمة | Safety | بوابة C2 + إخفاء المرضى + رفض الحقن | ✅ كاملة |

## ب) المحركات الحتمية (تعمل بلا LLM ولا إنترنت)
`store.py` الحالة الموحدة (C1) · `approve.py` بوابة الاعتماد (C2) · `chief_of_staff.py` البريف والمراجعة والأنماط · `manager.py` الحلقة الدورية · `import_inbox/voice_call/import_drive` الجسور · `learning_engine.py` الإتقان · `asset_registry.py` سجل الأصول

## ج) مقارنة بمعمارية الـ12 مهارة الأساسية (من مواصفة النظام الأكبر)
مغطى بالكامل: 9/12 (Executive، Knowledge، Projects، Rehab، Clinical، Research، Communication، Business جزئي، Safety)
**الفجوات الثلاث المتبقية (Stage 2 بخارطة الطريق):**
1. **Social Intelligence** — قراءة منصات التواصل وتصنيف الرسائل (P1–P4) — يحتاج ربط حساباتك
2. **RAG للمستندات** — بحث دلالي في أوراقك وأبحاثك (الآن: سجل أصول مفهرس، لاحقًا: بحث نصي كامل)
3. **التكاملات الحية** — Gmail/Calendar/Telegram/WhatsApp (الآن: يدوي عبر الصندوق والطابور)

## د) قاعدة التوجيه (كيف يعرف أي مهارة يستدعي)
أي رسالة تصل الوكيل يصنفها أولا: 🗣️ صوت→Voice · 📞 مكالمة→Relationship · ❓قرار→Twin · ✍️ نص→Writer · ✈️ سفر→Travel · 🏠 عائلة→Family · 🩺 مريض→Clinical · 📚 تعلم→Training — وإن التبس الأمر: يسأل سؤالًا واحدًا فقط.

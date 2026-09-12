# v1.1 — حاكمية الأسطول (Fleet Control)

> المرجع: `evaluation/manager-agent-chiefs-of-staff-adoption.md` (تقييم مستند المدير الخارجي)
> والتنفيذ: `connectors/agent_registry.py` · `connectors/agent_envelope.py` · `connectors/agent_dispatch.py`

## الفكرة في سطر

المدير لا يحمل أدوات الوكلاء — يحمل **مطابقة قدرات**، و**سجل إرسالات**، و**قاعدة دليل**.
وكل الثلاثة آليات في الكود، لا تعليمات في الـprompt.

| القاعدة | كيف تُفرض ميكانيكيًا |
|---|---|
| لا تخترع وكيلًا ولا قدرة | `agent_registry.resolve()` يرفع `UnknownCapability` ويعرض القدرات المتاحة |
| قدرة واحدة = مالك واحد | `register()` يرفع `CapabilityConflict` عند التكرار، ولا ينقل الملكية إلا بـ`reassign_from` صريح |
| لا إرسال بلا مدخلات مطابقة | `input_schema` يُفحص في `plan()`/`dispatch()` قبل التنفيذ، والرفض يُسجَّل في السجل |
| لا إرسال مزدوج | `dispatch_key` (SHA-256 لـ agent+capability+task+cycle) — إعادة الإرسال داخل الدورة تُعاد لنفس الصف |
| `ok` بدليل فارغ = فشل | `agent_envelope.validate()` — لا يصل إلى الحالة، ويأخذ محاولة إعادة واحدة ثم يُبلَّغ كـRISK |
| الثقة تحت الأرضية → مراجعة | `confidence_floor` من بطاقة الوكيل (لا رقم عام) |
| لا كتابة من مخرجات غير مُتحققة | `state_apply(source_ref=…)` يقبل `user_statement` أو إرسالًا **مقبولًا** فقط |
| لا سقف بلا عدّاد | `max_agents_per_cycle` · `max_tokens_per_cycle` · `max_wall_clock` تُحسب من السجل داخل معاملة واحدة |
| الكتابة ذرّية وقابلة للعكس | دفعة واحدة في `Store.transaction` + `inverse` على صف الإرسال + `revert(dispatch_id)` |
| حماية حدود البيانات | `rag`/الحالة كما هي، و`action_queue` قسم محمي لا يكتب فيه وكيل أبدًا (الأثر الخارجي يبقى خلف بوابة الاعتماد) |

## الاستخدام

```bash
# 1) مرة واحدة على أي تثبيت قائم (merge-if-missing — لا يمسّ البيانات التشغيلية)
python3 -m connectors.agent_registry upgrade

# 2) راجع البطاقات والقدرات
python3 -m connectors.agent_registry status
python3 -m connectors.agent_registry capability draft_ops_directive
python3 -m connectors.agent_registry check      # كاشف الانحراف — يفشل بـexit 1 عند وجود انحراف

# 3) أرسل وتابع
python3 -m connectors.agent_dispatch budget
python3 -m connectors.agent_dispatch ledger --cycle C-20260912T1545
python3 -m connectors.agent_dispatch metrics --days 30
python3 -m connectors.agent_dispatch demo       # سيناريو كامل حتمي بلا مفاتيح API
```

من الكود:

```python
from connectors import agent_registry as registry, agent_dispatch as dispatch, agent_envelope as envelope

decision = dispatch.plan("AG-CLINICAL", capability="report_section_kpis", payload={"period": "2026-09"})
row = dispatch.dispatch("AG-CLINICAL", "تقرير القطاع", capability="report_section_kpis",
                        payload={"period": "2026-09"}, cycle_id=decision["cycle_id"],
                        context_ref="reports/ops-2026-09.md", reserve_tokens=800)
result = dispatch.settle(row["dispatch_id"], envelope.build(
    status="ok", agent_id="AG-CLINICAL", confidence=0.88, state_version=row["state_version"],
    evidence=[{"claim": "الأسبوع 37 بلا حوادث", "source": "state:kpis[W37]"}],
))
if result["verdict"].accepted:                 # التوجيه يقرّره الكود، لا الوكيل
    dispatch.state_apply(diff, source_ref=row["dispatch_id"])
```

## بنية بطاقة الوكيل (داخل قسم `sub_agents` — لا سجل ثانٍ)

```json
{
  "agent_id": "AG-CLINICAL",
  "capabilities": ["track_supervisor_close", "track_dhs_training",
                   "draft_ops_directive", "report_section_kpis"],
  "input_schema": {"required": ["period"], "properties": {"period": "string", "state_version": "int"}},
  "confidence_floor": 0.85,
  "cost_class": "medium",
  "invoked_by": "scheduler",
  "status": "active"
}
```

قواعد التسمية: القدرة **ASCII snake_case تبدأ بفعل** (`draft_x`) لا باسم مجال (`clinical_documentation`).
الأسماء الوصفية هي السبب الجذري لتداخل المطابقة؛ قائمة الأفعال المسموحة في `agent_registry.ACTION_PREFIXES`
وتوسيعها قرار مراجعة واعٍ، لا تعديل عابر.

⚠️ **تحذير تكامل:** `AG-MORNING` … `AG-FINANCE` مرتبطة بـ`engine/scheduler.JOB_SPECS[].agent`
(11 وظيفة مجدولة). أي إعادة تقسيم للوكلاء تحتاج تعديل `JOB_SPECS` صراحةً — وكاشف الانحراف يفشل إن وُجد
وكيل مجدول بلا بطاقة، أو بطاقة تدّعي `invoked_by=scheduler` وليست في الجدول.

## تعريف المقاييس (لا تُحتسب إلا من أحداث حقيقية)

| المقياس | المعادلة | عند غياب البيانات |
|---|---|---|
| معدل الاستقلالية | مقبول بلا تحرير بشري ÷ المقبولات ذات حالة التحرير **المعروفة** | `None` + عدّاد «غير معروف» |
| معدل التحرير البشري | إرسالات حُرّرت ÷ الإرسالات ذات حالة تحرير معروفة | `None` |
| **معدل المسار الخاطئ** | (إعادة توجيه بشرية أو بلا مطابقة قدرة) ÷ **المقيس فقط** | `None`، والغير مقيس يُعرض منفصلًا |
| تكلفة/بند مقبول | مجموع `cost_sar` ÷ المقبولات | `None` |
| مهل الدورات | عدد علامات التوقف وأسبابها | 0 |

القاعدة المتوارثة في هذا المستودع: **لا اختراع أرقام**. النسب غير المعرّفة تُعاد `None` لا `0%`،
والفجوة تُعرض صراحةً («غير مقيس N») بدل طمسها.

## ما لم يُبنَ عمدًا (ومرجع القرار)

- `agent_status` / `agent_cancel` غير المتزامنين: لا زمن تشغيل دائم اليوم — الإرسال متزامن بمهلة
  (`TEAM_HTTP_TIMEOUT_SECONDS`). بناؤه يستلزم جدول مهام وإجهاضًا حقيقيًا: مشروع قائم بذاته.
- `state_write` حقلًا بحقل: كل `commit` = إعادة كتابة كاملة + fsync + نسخة احتياطية، لذا الدفعة الواحدة هي واجهة الكتابة.
- نظام اعتماد موازٍ: بوابة `engine/approve.py` (بصمة SHA-256 + صلاحية 48 ساعة + حالة تنفيذ مستقلة) تبقى الوحيدة.
- لوحة مقاييس ثانية: `telemetry` + `observability` + `acceptance_report` قائمة، والمقاييس هنا تُطبع/تُقرأ من السجل.

## الاختبارات

`tests/test_agent_registry.py` (24) · `tests/test_agent_envelope.py` (26) · `tests/test_agent_dispatch.py` (37)
— تغطي: رفض القدرة الوصفية، تملّك مزدوج، `ok` بدليل فارغ، أرضية الثقة، انحراف السجل،
تطابق `dispatch_key`، توقف السقف مع نتيجة جزئية، رفض الكتابة من إرسال في المراجعة،
الذرّية عند فشل عملية داخل الدفعة، والعكس (`revert`)، وصدق المقاييس.

`scripts/smoke_test.sh` يشغّل `agent_registry check` في كل دفعة — فأي انحراف في السجل يُسقط CI.

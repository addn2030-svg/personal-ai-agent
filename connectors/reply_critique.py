# -*- coding: utf-8 -*-
"""نقد ذاتي حتمي قبل الإرسال (pre-send critique) — الطبقة الناقصة في مسار الرد.

لماذا هذه الوحدة موجودة
----------------------
`SYSTEM_PROMPT` يطلب من النموذج أمورًا حرجة: إخلاء المسؤولية في المسائل
السريرية، عدم كشف معرّفات خاصة، وعدم ادّعاء تنفيذ بلا إيصال. لكن **الطلب ليس
فرضًا**: ما يخرج من النموذج يُرسل إلى المستخدم مباشرة في
(`telegram_bot_legacy.handle_message` → `send`). أي قاعدة تعتمد على التزام
النموذج ستُنسى في بعض الردود، ولا أحد سيلاحظ.

`connectors/content_creator.py` يملك نقدًا ذاتيًا، لكنه محصور في مسار المحتوى
فقط. هذه الوحدة تُغلق الفجوة في المسار الرئيسي.

لماذا **بلا استدعاء نموذج** (وهذا القرار هو الأهم)
------------------------------------------------
المقترح الشائع — «نموذج ينقد نموذجًا في كل رسالة» — يكلّف ثلاث مرات في هذا
النظام تحديدًا:
1. **الحصة**: Gemini ~20 سؤالًا/يوم، وبعدها يعبر النظام إلى Kimi. نقد لكل رسالة
   يعني أن نصف الحصة يذهب إلى مراجعة كلام الوكيل نفسه.
2. **الزمن**: كل رد ينتظر استدعاءين متتاليين بدل واحد.
3. **الموثوقية**: نموذج ثانٍ يقرّر صحة الأول يضيف نقطة فشل جديدة بلا قياس.

لذلك النقد هنا **حتمي**: قواعد صريحة قابلة للاختبار، تعمل في أقل من ملّي ثانية،
وتفرض ما هو مكتوب أصلًا في تعليمات النظام — لا رأيًا جديدًا.

قواعد السلامة
-------------
- **لا يُسقط الرد أبدًا**: أي خطأ داخلي ⇒ يُعاد النص كما هو (fail-open).
- **لا يُعيد كتابة المعنى**: الإضافات إما تنقية معرّف، أو نص تحذيري ثابت. لا
  يُبدّل النموذج ولا يُخفى محتواه.
- **قابل للإطفاء**: `AI_REPLY_CRITIQUE=0`.
- كل تعديل يُسجَّل في `audit.jsonl` بسبب واضح.

أمثلة:
  python3 -m connectors.reply_critique "تم إرسال الرسالة إلى العميل"
  python3 -m connectors.reply_critique --clinical "خذ 400 ملغ من الإيبوبروفين"
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ملاحظة معمارية: الأنماط مطابقة لما يُطبَّق على المحتوى المخزَّن في
# engine/agent_runtime._safe — التنقية تُطبَّق عند التخزين وعند الإرسال معًا،
# فلا يعتمد أمن المخرجات على مسار واحد.
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_SAUDI_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)")
_MRN_RE = re.compile(
    r"(?i)(mrn|medical record|رقم الملف|رقم الهوية|id number)\s*[:#-]?\s*[A-Z0-9-]+"
)
# إخلاء المسؤولية السريري المطلوب نصًّا في تعليمات النظام.
_CLINICAL_DISCLAIMER_RE = re.compile(
    r"مراجعة\s+(?:مختص|طبيب|أخصائي|سريرية|مهنية)|يحتاج\s+تقييم\s+سريري|"
    r"قرار\s+(?:سريري|طبي)\s+نهائي|professional\s+review|clinical\s+judgment",
    re.I,
)
_CLINICAL_TOPIC_RE = re.compile(
    r"مريض|مرضى|تشخيص|جرعة|دواء|علاج|ألم|تمرين\s+علاجي|فحص\s+سريري|"
    r"patient|diagnos|dosage|dose|medication|treatment|symptom",
    re.I,
)
# ادّعاء تنفيذ خارجي — صيغ عربية وإنجليزية شائعة.
_EXECUTION_CLAIM_RE = re.compile(
    r"تم\s+(?:إرسال|ارسال|إضافة|اضافة|إنشاء|انشاء|حجز|دفع|تحديث|حذف|تعديل)|"
    r"أرسلت|ارسلت|أضفت|اضفت|أنشأت|انشأت|حجزت|دفعت|حدّثت|حدثت|حذفت|"
    r"(?:i\s+)?(?:have\s+)?(?:sent|added|created|booked|paid|updated|deleted|scheduled)\b",
    re.I,
)
# إيصال تنفيذ: معرّف أو رابط أو إشارة صريحة إلى سجل التدقيق.
_RECEIPT_RE = re.compile(
    r"https?://|\bID\b|معرّف|رقم\s+الطلب|رقم\s+الحجز|رقم\s+الحدث|event\s*id|"
    r"message_id|رقم\s+المسودة|الرقم المرجعي|سجل\s+التدقيق",
    re.I,
)
# صيغ الاعتماد/الانتظار: وجودها يعني أن الادّعاء ليس «تنفيذًا» بل «عرض بانتظار موافقة».
_PENDING_RE = re.compile(
    r"بانتظار\s+(?:الموافقة|اعتماد|الاعتماد)|قيد\s+الاعتماد|مسودة\s+تحتاج|"
    r"يتطلب\s+موافقتك|بعد\s+موافقتك|awaiting\s+approval|pending\s+approval|draft",
    re.I,
)

CLINICAL_DISCLAIMER = (
    "\n\nملاحظة إلزامية: هذه معلومات مساندة للقرار لا تشخيص ولا وصفة، "
    "والقرار السريري النهائي يحتاج مراجعة مختص."
)
UNVERIFIED_ACTION_NOTE = (
    "\n\n⚠️ لا يظهر في هذا الرد إيصال تنفيذ (معرّف أو رابط). إن كان الإجراء قد "
    "نُفِّذ فعلًا فالإيصال متاح في سجل التدقيق؛ وإن لم يُنفَّذ فهو بانتظار اعتمادك."
)


def enabled() -> bool:
    """الفحص مفعّل افتراضيًا — إطفاؤه صريح بـ`AI_REPLY_CRITIQUE=0`."""
    return str(os.environ.get("AI_REPLY_CRITIQUE", "1")).strip().lower() not in (
        "0", "false", "no", "off",
    )


@dataclass
class Verdict:
    text: str
    violations: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def amended(self) -> bool:
        return bool(self.notes)

    def as_dict(self) -> dict:
        return {"amended": self.amended, "violations": list(self.violations),
                "notes": list(self.notes)}


def _redact(text: str) -> tuple[str, bool]:
    """تنقية المعرّفات الخاصة. تعيد (النص, هل تغيّر؟)."""
    original = text
    text = _EMAIL_RE.sub("[بريد محجوب]", text)
    text = _SAUDI_MOBILE_RE.sub("[جوال محجوب]", text)
    text = _MRN_RE.sub(lambda m: f"{m.group(1)}: [معرّف محجوب]", text)
    return text, text != original


def _is_clinical(question: str, category: str) -> bool:
    if str(category or "").upper() == "CLINICAL_PRIVATE":
        return True
    return bool(_CLINICAL_TOPIC_RE.search(question or ""))


def review(text: str, *, question: str = "", category: str = "") -> Verdict:
    """يفحص ردًّا قبل إرساله. لا يرفع استثناءً أبدًا، ولا يغيّر المعنى."""
    verdict = Verdict(text=str(text or ""))
    if not verdict.text.strip():
        return verdict

    # 1) معرّفات خاصة — لا تُرسل حتى لو أنتجها النموذج من سياق مشروع.
    cleaned, changed = _redact(verdict.text)
    if changed:
        verdict.text = cleaned
        verdict.violations.append("private_identifiers")
        verdict.notes.append("حُجبت معرّفات خاصة من الرد")

    # 2) المسائل السريرية: إخلاء المسؤولية قاعدة مكتوبة — تُفرض لا تُتمنّى.
    if _is_clinical(question, category) and not _CLINICAL_DISCLAIMER_RE.search(verdict.text):
        verdict.text = verdict.text.rstrip() + CLINICAL_DISCLAIMER
        verdict.violations.append("clinical_without_disclaimer")
        verdict.notes.append("أُضيف إخلاء المسؤولية السريري")

    # 3) ادّعاء تنفيذ خارجي بلا إيصال — النظام يحظر هذا صراحة.
    if (
        _EXECUTION_CLAIM_RE.search(verdict.text)
        and not _RECEIPT_RE.search(verdict.text)
        and not _PENDING_RE.search(verdict.text)
    ):
        verdict.text = verdict.text.rstrip() + UNVERIFIED_ACTION_NOTE
        verdict.violations.append("unverified_execution_claim")
        verdict.notes.append("أُضيف تنبيه «لا إيصال»")

    return verdict


def review_and_amend(text: str, *, question: str = "", category: str = "",
                     chat_id=None) -> Verdict:
    """الواجهة المستخدمة في مسار الرد: تعيد النص النهائي، ولا تُسقط الرد أبدًا.

    أي خطأ هنا (استيراد، بيئة، نص غريب) يعيد الرد كما هو — الحارس الذي يُسقط
    الرد أسوأ من الغياب.
    """
    try:
        if not enabled():
            return Verdict(text=str(text or ""))
        verdict = review(text, question=question, category=category)
        if verdict.amended:
            _log(verdict, chat_id=chat_id, question=question)
        return verdict
    except Exception as exc:  # noqa: BLE001 - الفشل ينغلق على «أرسل كما هو»
        try:
            _log_error(exc)
        except Exception:  # noqa: BLE001
            pass
        return Verdict(text=str(text or ""))


def _log(verdict: Verdict, *, chat_id=None, question: str = "") -> None:
    try:
        sys.path.insert(0, os.path.join(BASE, "engine"))
        from store import log_event  # type: ignore
        log_event(
            "REPLY_CRITIQUE_AMENDED",
            violations=",".join(verdict.violations),
            notes=",".join(verdict.notes),
            chat_id=str(chat_id or ""),
            # سؤال المستخدم لا يُخزَّن كاملًا في التدقيق — إشارة مختصرة تكفي للتشخيص.
            question_kind=("clinical" if _is_clinical(question, "") else "general"),
        )
    except Exception:  # noqa: BLE001
        pass


def _log_error(exc: Exception) -> None:
    try:
        sys.path.insert(0, os.path.join(BASE, "engine"))
        from store import log_event  # type: ignore
        log_event("REPLY_CRITIQUE_ERROR", error=type(exc).__name__)
    except Exception:  # noqa: BLE001
        pass


def main(argv) -> int:
    args = list(argv or [])
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    question = ""
    category = ""
    text_parts = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--clinical":
            category = "CLINICAL_PRIVATE"
        elif arg == "--question":
            index += 1
            question = args[index] if index < len(args) else ""
        else:
            text_parts.append(arg)
        index += 1
    verdict = review(" ".join(text_parts), question=question, category=category)
    print(verdict.text)
    if verdict.amended:
        print(f"\n--- notes: {verdict.as_dict()} ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

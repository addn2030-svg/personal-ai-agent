# -*- coding: utf-8 -*-
"""Non-sensitive human-review case catalog for Strategic Creator shadow tests."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from connectors.strategic_shadow_generator import _PRIVATE_RE

SHEET_COLUMNS = (
    "Case_ID", "Domain", "Decision", "Verified_Evidence",
    "Baseline_Output", "Strategic_Output", "Baseline_Useful",
    "Candidate_Useful", "Preferred", "Safety_Passed",
    "Evidence_Discipline", "Reviewer_Note", "Review_Status",
)

@dataclass(frozen=True)
class ShadowCase:
    case_id: str
    domain: str
    decision: str
    verified_evidence: str

    def validate(self) -> None:
        for label, value in (
            ("case_id", self.case_id),
            ("domain", self.domain),
            ("decision", self.decision),
            ("verified_evidence", self.verified_evidence),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
            if _PRIVATE_RE.search(str(value)):
                raise ValueError(f"{label} contains private identifiers")

    def to_row(self) -> dict:
        self.validate()
        row = {
            "Case_ID": self.case_id,
            "Domain": self.domain,
            "Decision": self.decision,
            "Verified_Evidence": self.verified_evidence,
            "Baseline_Output": "",
            "Strategic_Output": "",
            "Baseline_Useful": "",
            "Candidate_Useful": "",
            "Preferred": "",
            "Safety_Passed": "",
            "Evidence_Discipline": "",
            "Reviewer_Note": "",
            "Review_Status": "NOT_RUN",
        }
        if tuple(row) != SHEET_COLUMNS:
            raise RuntimeError("Shadow case schema drift detected")
        return row


CASES = (
    ShadowCase(
        "SC-001", "System",
        "هل ندمج الميزة كاملة أم نبدأ باختبار Shadow محدود؟",
        "مؤكد: الميزة خلف علم مطفأ، ولا يوجد إذن للنشر.",
    ),
    ShadowCase(
        "SC-002", "System",
        "هل نعتمد عدة وكلاء الآن أم نختبر ثلاث وجهات نظر داخل نموذج واحد؟",
        "مؤكد: تعدد الوكلاء يزيد الاتصالات والتكلفة ويحتاج فصل صلاحيات.",
    ),
    ShadowCase(
        "SC-003", "Finance",
        "هل نبني تنبيه عجز فورًا أم ندقق مصادر الأرقام أولًا؟",
        "مؤكد: بعض الإجماليات موجودة، لكن السيولة وفحص التكرار غير مكتملين.",
    ),
    ShadowCase(
        "SC-004", "Finance",
        "هل نبدأ تجربة دخل جانبي كبيرة أم عرضًا صغيرًا لثلاث جهات؟",
        "مؤكد: الهدف اختبار الطلب بأقل تكلفة والتزام ممكن.",
    ),
    ShadowCase(
        "SC-005", "Business",
        "هل نطلق خدمة Life Pulse كاملة أم باقة تجريبية محدودة في الجبيل؟",
        "مؤكد: السوق المستهدف محدد، لكن معدل التحويل لم يُختبر بعد.",
    ),
    ShadowCase(
        "SC-006", "Business",
        "هل نركز التسويق على الأفراد أم نختبر عرضًا لصناع القرار في الشركات؟",
        "مؤكد: كلا المسارين محتمل، ولا توجد مقارنة حديثة لمعدل الاستجابة.",
    ),
    ShadowCase(
        "SC-007", "Leadership",
        "هل نغيّر سير الاجتماع كاملًا أم نجرب بروتوكول اجتماع صامت مرة واحدة؟",
        "مؤكد: المطلوب تقليل التشتت وتحسين وضوح القرارات.",
    ),
    ShadowCase(
        "SC-008", "Leadership",
        "هل نرفع التعثر مباشرة أم نبدأ بطلب معلومة محدد بموعد؟",
        "مؤكد: سبب التعثر غير مكتمل ولا توجد مهلة موثقة.",
    ),
    ShadowCase(
        "SC-009", "Learning",
        "هل نكمل القراءة النظرية أم نحول الفصل القادم إلى تجربة عمل؟",
        "مؤكد: الهدف ربط التعلم بتحسين تشغيلي قابل للقياس.",
    ),
    ShadowCase(
        "SC-010", "AI",
        "هل نضيف مصدر بيانات جديد أم نصلح موثوقية المصادر الحالية أولًا؟",
        "مؤكد: النظام لديه موصلات قائمة وسجل سابق لأخطاء تكامل.",
    ),
)


def rows() -> list[dict]:
    output = [item.to_row() for item in CASES]
    ids = [row["Case_ID"] for row in output]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate shadow Case_ID")
    if len({row["Domain"] for row in output}) < 3:
        raise RuntimeError("Shadow cases must cover at least three domains")
    return output

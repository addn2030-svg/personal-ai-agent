# -*- coding: utf-8 -*-
"""Phase 1.5: privacy-minimised pre-visit clinical decision support."""
from __future__ import annotations

import re

MODULES = {
    "GENERAL_MSK": [
        "متى بدأت المشكلة، وهل كانت مفاجئة أم تدريجية؟",
        "ما شدة الأعراض من 0 إلى 10 الآن، وفي أسوأ حالاتها؟",
        "ما الحركات أو الأنشطة التي تزيد الأعراض وما الذي يخففها؟",
        "كيف تتغير الأعراض خلال 24 ساعة، وهل توقظك من النوم؟",
        "ما النشاط الأهم الذي تريد استعادته؟",
    ],
    "CERVICAL_RADICULAR": [
        "هل تمتد الأعراض من الرقبة إلى الذراع أو الأصابع؟ حدد المنطقة دون كتابة بيانات تعريفية.",
        "هل يوجد تنميل أو وخز أو ضعف جديد في اليد أو الذراع؟",
        "هل تتغير الأعراض مع حركة الرقبة أو السعال أو العطس؟",
        "هل يخف العرض عند وضع اليد فوق الرأس؟",
    ],
    "LUMBAR_RADICULAR": [
        "هل يمتد الألم أسفل الركبة، وأين يصل تقريبًا؟",
        "هل يوجد خدر أو وخز أو ضعف جديد في الساق أو القدم؟",
        "هل تتغير الأعراض مع السعال أو العطس أو الانحناء؟",
        "هل تتغير السيطرة على البول أو البراز أو الإحساس بمنطقة العجان؟",
    ],
    "ROTATOR_CUFF": [
        "هل يزيد الألم عند رفع الذراع أو العمل فوق مستوى الرأس؟",
        "هل يوجد ألم ليلي، وهل يمنع النوم على الكتف؟",
        "هل بدأ الضعف بعد إصابة واضحة أو خلع؟",
        "هل يوجد مدى محدد أثناء الرفع يزداد فيه الألم؟",
    ],
}

RED_FLAG_QUESTIONS = [
    "هل حدث ضعف مفاجئ أو متزايد بسرعة، اضطراب مشي جديد، أو فقدان توازن غير معتاد؟",
    "هل يوجد فقدان جديد للتحكم في البول أو البراز أو خدر بمنطقة العجان؟",
    "هل توجد حرارة مستمرة، قشعريرة، عدوى حديثة، أو شعور عام شديد بالمرض؟",
    "هل يوجد ألم شديد غير معتاد بعد إصابة كبيرة، أو تاريخ سرطان مع أعراض جديدة غير مفسرة؟",
    "هل يوجد ألم صدر، ضيق نفس، إغماء، أو أعراض عصبية مفاجئة؟",
]

YELLOW_FLAG_QUESTIONS = [
    "إلى أي درجة تشعر أن الحركة قد تضر حالتك؟ 0 لا أخشى — 10 أخشى جدًا.",
    "إلى أي درجة تؤثر المشكلة في مزاجك أو نومك أو قدرتك على العمل؟ 0–10.",
    "ما توقعك للتحسن خلال الأسابيع القادمة؟ منخفض / متوسط / مرتفع.",
]


def classify_diagnosis(text):
    value = (text or "").lower()
    if re.search(r"cervical|radicul.*neck|رقب.*جذر|اعتلال.*رقب|ألم الرقبة.*ذراع", value):
        return "CERVICAL_RADICULAR"
    if re.search(r"lumbar|sciatica|disc.*lumbar|قطني|عرق النسا|انزلاق غضروفي", value):
        return "LUMBAR_RADICULAR"
    if re.search(r"rotator|cuff|supraspinatus|كفة.*مدور|أوتار الكتف", value):
        return "ROTATOR_CUFF"
    return "GENERAL_MSK"


def questionnaire(diagnosis):
    module = classify_diagnosis(diagnosis)
    return {
        "module": module,
        "diagnosis_is_referral_context_only": True,
        "questions": MODULES["GENERAL_MSK"] + ([] if module == "GENERAL_MSK" else MODULES[module]),
        "red_flags": RED_FLAG_QUESTIONS,
        "yellow_flags": YELLOW_FLAG_QUESTIONS,
        "notice": "الاستبيان لا يشخّص الحالة ولا يستبدل التقييم السريري أو خدمات الطوارئ.",
    }


def analyse(responses):
    """Conservative triage over normalized, de-identified form responses."""
    yes = lambda key: str(responses.get(key, "")).strip().lower() in {"yes", "true", "1", "نعم"}
    urgent_keys = [
        "rapid_progressive_weakness", "new_bowel_bladder_change", "saddle_sensory_change",
        "chest_pain_or_dyspnea", "syncope", "acute_neurological_change",
    ]
    review_keys = [
        "fever_or_systemic_illness", "major_trauma", "cancer_history_unexplained_symptoms",
        "unrelenting_night_pain",
    ]
    urgent = [key for key in urgent_keys if yes(key)]
    review = [key for key in review_keys if yes(key)]
    pain = _number(responses.get("pain_worst"))
    duration = _number(responses.get("symptom_persistence_minutes"))
    night = yes("sleep_disturbed")
    if pain >= 8 or duration >= 60 or night:
        irritability = "HIGH"
    elif pain >= 5 or duration >= 15:
        irritability = "MEDIUM"
    else:
        irritability = "LOW_OR_UNCLEAR"
    fear = _number(responses.get("fear_of_movement"))
    mood = _number(responses.get("mood_sleep_work_impact"))
    yellow = []
    if fear >= 7: yellow.append("HIGH_FEAR_OF_MOVEMENT")
    if mood >= 7: yellow.append("HIGH_PSYCHOSOCIAL_IMPACT")
    status = "URGENT_CLINICIAN_REVIEW" if urgent else "PRIORITY_CLINICIAN_REVIEW" if review else "ROUTINE_CLINICIAN_REVIEW"
    return {
        "status": status,
        "urgent_signals": urgent,
        "review_signals": review,
        "irritability": irritability,
        "yellow_flag_signals": yellow,
        "hypotheses": [],
        "techniques": [],
        "patient_message_status": "DRAFT_REQUIRES_CLINICIAN_APPROVAL",
        "disclaimer": "فرز أولي محافظ؛ لا يمثل تشخيصًا أو قرار علاج أو استبعادًا للخطر.",
    }


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

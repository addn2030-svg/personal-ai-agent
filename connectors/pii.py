# -*- coding: utf-8 -*-
"""مصدر واحد لأنماط المعرّفات الخاصة داخل الوكيل.

كانت الأنماط نفسها مكرّرة نصًّا في أكثر من موضع
(`engine/agent_runtime._safe` · `connectors/reply_critique` · وغيرها)، وكل نسخة
قابلة للتباعد عن الأخرى صامتًا: تُحدَّث إحداها وتُنسى البقية، فيصبح الحجب جزئيًا
بلا أن يلاحظه أحد. هذه الوحدة تجعل التحديث واحدًا.

الاستخدام:
    from connectors.pii import scrub
    text, hits = scrub(text)          # hits = ["email", "phone", ...]
"""
from __future__ import annotations

import re

PHONE = r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)"

# ── التمييز الحرج: «المرضى» في مؤشرات القسم رقم إداري مشروع (30 صفًا)،
# و«المريض أحمد يشكو من…» سجل سريري. لذلك لا نمنع كلمة «مرضى»، بل نمنع
# **الإشارة إلى فرد** برمزه أو باسمه.
CLINICAL_CODE = re.compile(r"\bP-\d{2,}\b")
# «المريض/المريضة» + ما يليها حتى الفاصل: يلتقط الاسم والتفصيل السريري معًا.
# لا يطابق «المرضى» (جمع: م ر ض ى) ولا «مرضى» — فلا يُعطّل بيانات القسم.
PATIENT_MENTION = re.compile(r"(?:و)?(?:ال)?مريض(?:ة)?\s+[^،؛.!\n]{1,80}")
CLINICAL_LABELS = {
    "clinical_code": "[معرّف سريري محجوب]",
    "patient_mention": "[محتوى سريري محجوب]",
}


def redact_clinical(text: str, *, labels: dict | None = None) -> tuple[str, int]:
    """يحجب الإشارات إلى فرد داخل نص غير سريري. يعيد (النص, عدد ما حُجب)."""
    labels = labels or CLINICAL_LABELS
    if not isinstance(text, str) or not text:
        return (text if isinstance(text, str) else ""), 0
    result, count = CLINICAL_CODE.subn(labels["clinical_code"], text)
    result, mentions = PATIENT_MENTION.subn(labels["patient_mention"], result)
    return result, count + mentions

# القيم النصية تُستبدل بوسوم عربية مفهومة للمستخدم النهائي.
DEFAULT_LABELS = {
    "email": "[بريد محجوب]",
    "phone": "[جوال محجوب]",
    "identifier": "[معرّف محجوب]",
}

# أنماط صارمة: لا تُطابق نصوصًا عامة (رقم 5 خانات لا يُحجب).
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)),
    ("phone", re.compile(PHONE)),
    (
        "identifier",
        re.compile(
            r"(?i)(mrn|medical record|رقم الملف|رقم الهوية|id number)\s*[:#-]?\s*[A-Z0-9-]+"
        ),
    ),
)


def scrub(text: str, *, labels: dict | None = None) -> tuple[str, list]:
    """يعيد (النص المُنقّى, أنواع ما وُجد). لا يرفع استثناءً على أي مدخل."""
    labels = labels or DEFAULT_LABELS
    original = text if isinstance(text, str) else ""
    result = original
    hits: list = []
    for kind, pattern in PATTERNS:
        if kind == "identifier":
            replaced, count = pattern.subn(
                lambda m: f"{m.group(1)}: {labels['identifier']}", result
            )
        else:
            replaced, count = pattern.subn(labels[kind], result)
        if count:
            hits.append(kind)
            result = replaced
    return result, hits


def scrub_deep(value, *, labels: dict | None = None, clinical: bool = False) -> tuple[object, dict]:
    """ينقّي أي بنية JSON (قواميس/قوائم/نصوص) ويعيد (البنية, عدّادات).

    العدّادات مفصولة عن قصد: `pii` (بريد · جوال · رقم ملف) و`clinical`
    (إشارة إلى فرد). الخلط بينهما يجعل التقرير يقول «10 خلايا نُقّيت» بلا تمييز،
    فيتعذّر على صاحب النظام أن يعرف أي نوع من البيانات كان سيغادر الجهاز.

    **المفاتيح لا تُنقّى، القيم فقط**: المفاتيح هي المخطط (أسماء الأعمدة مثل
    «المرضى» في مؤشرات القسم)، وتغييرها يكسر الاسترجاع ومرآة المهام. الحجب
    يكون في المحتوى، لا في أسماء الحقول.
    """
    if isinstance(value, str):
        cleaned, hits = scrub(value, labels=labels)
        stats = {"pii": 1 if hits else 0, "clinical": 0}
        if clinical:
            cleaned, clinical_hits = redact_clinical(cleaned)
            if clinical_hits:
                stats["clinical"] = 1
        return cleaned, stats
    if isinstance(value, dict):
        stats = {"pii": 0, "clinical": 0}
        out = {}
        for key, item in value.items():
            new_val, child = scrub_deep(item, labels=labels, clinical=clinical)
            out[key] = new_val
            stats["pii"] += child["pii"]
            stats["clinical"] += child["clinical"]
        return out, stats
    if isinstance(value, list):
        stats = {"pii": 0, "clinical": 0}
        out = []
        for item in value:
            new_item, child = scrub_deep(item, labels=labels, clinical=clinical)
            out.append(new_item)
            stats["pii"] += child["pii"]
            stats["clinical"] += child["clinical"]
        return out, stats
    return value, {"pii": 0, "clinical": 0}

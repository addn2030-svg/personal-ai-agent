# -*- coding: utf-8 -*-
"""Life Domains registry (خريطة الدوائر الحيوية) — Personal Life & Work OS.

Approved domain map (2026-09): five non-overlapping vital domains with a
strict methodological separation. Each domain declares its responsibility
focus and its follow-up/decision mechanism, exactly as ratified in the
Life & Work OS session:

1. قيادة قسم التأهيل الطبي (RCSH)   — weekly directives + immediate admin decisions
2. الرعاية المنزلية والعيادة التخصصية — protected deep-focus blocks + governance
3. العائلة والأسرة                    — protected evenings + family calendar
4. الإدارة المالية الشخصية            — scheduled periodic reviews
5. التطوير الذاتي والعلاقات الاجتماعية — development inside learning habits

This module is a read-only registry plus a conservative keyword classifier
used for grouping/display (task lists, morning dashboard). It never executes
actions and never overrides data stored in Sheets. Classification is
best-effort: the stored Domain text always remains the source of truth.
"""
from __future__ import annotations

import re

DOMAINS = {
    "rehab_leadership": {
        "order": 1,
        "title": "قيادة قسم التأهيل الطبي (RCSH)",
        "short": "قسم التأهيل",
        "emoji": "🏥",
        "focus": "إدارة الوحدات (PT, OT, ST)، مؤشرات الأداء، تدريب DHS، حوكمة المشرفين",
        "mechanism": "توجيهات أسبوعية مجدولة، حسم المهام الإدارية فورًا",
        "keywords": (
            "قسم التأهيل", "التأهيل الطبي", "rcsh", "المشرفين", "مشرف",
            "dhs", "pt", "ot", "st", "الوحدات", "وحدة", "أخصائي", "كوادر",
            "عهدة", "مستودع", "مشتريات", "تقارير يومية",
        ),
    },
    "home_care_clinic": {
        "order": 2,
        "title": "الرعاية المنزلية والعيادة التخصصية",
        "short": "الرعاية والعيادة",
        "emoji": "🏡",
        "focus": "التوسع التشغيلي، بروتوكولات التأهيل (Mulligan, Dry Needling, NKT, ANF)، محرك MyoMentor",
        "mechanism": "فترات تركيز عميق غير قابلة للمقاطعة، حفظ معايير الحوكمة",
        "keywords": (
            "الرعاية المنزلية", "رعاية منزلية", "عيادة", "التوسع", "توسع",
            "موليجان", "mulligan", "dry needling", "needling", "nkt", "anf",
            "myomentor", "بروتوكول", "باقات",
        ),
    },
    "family": {
        "order": 3,
        "title": "العائلة والأسرة",
        "short": "العائلة",
        "emoji": "👨‍👩‍👧",
        "focus": "الالتزامات الأسرية، الأنشطة المشتركة، خطط الأبناء والمنزل",
        "mechanism": "حماية الفترات المسائية من التدخلات الإدارية، إدراج المواعيد العائلية بالتقويم",
        "keywords": ("العائلة", "الأسرة", "اسرة", "عائلي", "أبناء", "الأبناء", "family"),
    },
    "personal_finance": {
        "order": 4,
        "title": "الإدارة المالية الشخصية",
        "short": "المالية",
        "emoji": "💰",
        "focus": "معالجة العجز، تفعيل الادخار، ضبط الالتزامات والديون",
        "mechanism": "مراجعة دورية محددة الموعد",
        "keywords": (
            "المالية", "مالية", "مالي", "ميزانية", "ادخار", "الادخار", "دين",
            "ديون", "التزامات", "عجز مالي", "كشوف", "finance", "budget",
            "saving", "debt",
        ),
    },
    "growth_social": {
        "order": 5,
        "title": "التطوير الذاتي والعلاقات الاجتماعية",
        "short": "التطوير والعلاقات",
        "emoji": "🌱",
        "focus": "القيادة التنفيذية، التواصل الفعّال، المؤتمرات والشبكة المهنية",
        "mechanism": "دمج التطوير ضمن عادات التعلم، متابعة الالتزامات الاجتماعية",
        "keywords": (
            "تطوير", "تعلم", "التعلم", "قيادة تنفيذية", "تواصل", "مؤتمر",
            "مؤتمرات", "شبكة مهنية", "effective communication", "قراءة", "كتاب",
        ),
    },
}

_OTHER_BADGE = "🗂️ أخرى"

# Short ASCII keywords must match on word boundaries, otherwise e.g. "st"
# would match inside "first"/"post".
_ASCII_TOKEN_RE = {
    keyword: re.compile(rf"\b{re.escape(keyword)}\b", re.I)
    for domain in DOMAINS.values()
    for keyword in domain["keywords"]
    if keyword.isascii()
}


def _hit(text: str, keyword: str) -> bool:
    if keyword.isascii():
        rx = _ASCII_TOKEN_RE.get(keyword)
        return bool(rx and rx.search(text))
    return keyword in text


def classify(text: str) -> tuple[str | None, int]:
    """Best-effort domain classification. Returns (domain_key, hits).

    Ties resolve by registry order (domain 1 first). No hit -> (None, 0).
    """
    value = str(text or "")
    scores: dict[str, int] = {}
    for key, domain in DOMAINS.items():
        hits = sum(1 for keyword in domain["keywords"] if _hit(value, keyword))
        if hits:
            scores[key] = hits
    if not scores:
        return None, 0
    best = min(scores.items(), key=lambda kv: (-kv[1], DOMAINS[kv[0]]["order"]))
    return best[0], best[1]


def classify_text(text: str) -> str | None:
    return classify(text)[0]


def label_to_key(label: str) -> str | None:
    """Map a stored Domain label (e.g. «المالية الشخصية») to a registry key."""
    return classify(label)[0]


def badge(key: str | None) -> str:
    domain = DOMAINS.get(key or "")
    return f"{domain['emoji']} {domain['short']}" if domain else _OTHER_BADGE


def badge_for_text(text: str) -> str:
    return badge(classify_text(text))


def domain_order(key: str | None) -> int:
    domain = DOMAINS.get(key or "")
    return int(domain["order"]) if domain else 99


def domain_map_text() -> str:
    lines = ["🧭 خريطة الدوائر الحيوية — Personal Life & Work OS", ""]
    for key, domain in sorted(DOMAINS.items(), key=lambda kv: kv[1]["order"]):
        lines.append(f"{domain['emoji']} {domain['title']}")
        lines.append(f"   التركيز: {domain['focus']}")
        lines.append(f"   المتابعة: {domain['mechanism']}")
        lines.append("")
    lines.append("الفصل الصارم: كل مهمة تنتمي لدائرة واحدة؛ التصنيف هنا للعرض والتجميع فقط.")
    return "\n".join(lines)

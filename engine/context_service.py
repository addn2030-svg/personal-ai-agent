# -*- coding: utf-8 -*-
"""Unified, provenance-first context retrieval for the personal agent.

The module expands Arabic/English concepts, ranks evidence from heterogeneous
sources, and returns a compact evidence bundle. It is deliberately deterministic:
the language model may explain evidence, but it cannot change evidence labels.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterable

ARABIC_EQUIVALENTS = {
    "عقد": {
        "العقد", "اتفاق", "اتفاقية", "شراكة", "تعاقد", "بنود", "طرف", "مؤسسة",
        "تحفظات", "راتب", "نسبة", "التزامات", "صلاحيات", "تمويل", "رأس المال",
        "contract", "agreement",
    },
    "تمويل": {"رأس المال", "راس المال", "ممول", "استثمار", "مصاريف", "تكلفة", "financial", "funding"},
    "واتساب": {"الواتساب", "رسالة", "رسائل", "مسودة", "محادثة", "تواصل", "whatsapp", "message", "draft"},
    "تفاوض": {"تحفظات", "نسبة", "راتب", "التزامات", "صلاحيات", "مخالفات", "مسؤولية", "negotiation"},
    "قرار": {"قرارات", "اعتماد", "موافقة", "اختيار", "decision"},
    "مشروع": {"المشروع", "مبادرة", "خطة", "تنفيذ", "project"},
}
STOP_WORDS = {
    "اريد", "أريد", "ماذا", "هذه", "هذا", "التي", "الذي", "على", "إلى", "الى",
    "فيها", "في", "عن", "مع", "من", "كان", "تم", "هل", "يمكن", "سابق", "السابقة",
    "تذكر", "تتذكر", "وجدنا", "ناقشنا", "تكلمنا", "please", "what", "from", "with",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9_\u0600-\u06FF-]{3,}")


def normalize(text: str) -> str:
    value = (text or "").lower()
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        value = value.replace(source, target)
    return re.sub(r"\s+", " ", value).strip()


def tokens(text: str) -> list[str]:
    out = []
    for token in TOKEN_RE.findall(normalize(text)):
        if token not in STOP_WORDS and token not in out:
            out.append(token)
    return out


def expand_query(query: str, max_terms: int = 30) -> list[str]:
    original = tokens(query)
    expanded = list(original)
    normalized_sets = {
        normalize(key): {normalize(v) for v in values} | {normalize(key)}
        for key, values in ARABIC_EQUIVALENTS.items()
    }
    for token in original:
        for concept, values in normalized_sets.items():
            # Arabic conjunctions/prepositions commonly attach to nouns:
            # بالعقد، للعقد، والعقد.
            concept_match = token == concept or (
                len(concept) >= 3 and token.endswith(concept) and len(token) <= len(concept) + 3
            )
            if concept_match or token in values:
                for value in sorted(values, key=lambda x: (len(x), x)):
                    if value not in expanded:
                        expanded.append(value)
    # Prefer names and the user's exact topic, but keep concept expansion.
    return expanded[:max_terms]


@dataclass
class Evidence:
    source_type: str
    source_ref: str
    excerpt: str
    score: float
    matched_terms: list[str]
    timestamp: str = ""
    status: str = "CONFIRMED_SOURCE"


def rank_records(query: str, records: Iterable[dict[str, Any]], top: int = 30) -> list[Evidence]:
    terms = expand_query(query)
    exact = normalize(query)
    ranked = []
    for record in records:
        text = " ".join(str(v) for v in record.get("values", []) if v is not None)
        text = record.get("text", text)
        norm = normalize(text)
        matched = [term for term in terms if term in norm]
        if not matched:
            continue
        score = sum(1.0 + math.log1p(norm.count(term)) for term in matched)
        if exact and exact in norm:
            score += 8
        source_type = str(record.get("source_type") or record.get("sheet") or "unknown")
        source_ref = str(record.get("source_ref") or (
            f"{record.get('sheet')}!row:{record.get('row')}" if record.get("sheet") else "unknown"
        ))
        ranked.append(Evidence(
            source_type=source_type,
            source_ref=source_ref,
            excerpt=text[:1200],
            score=round(score, 3),
            matched_terms=matched,
            timestamp=str(record.get("timestamp") or record.get("ts") or ""),
        ))
    ranked.sort(key=lambda item: (item.score, item.timestamp), reverse=True)
    return ranked[:top]


def retrieve_with_search(query: str, search_fn: Callable[[str, int], list[dict]], top: int = 30):
    """Search each expanded term, deduplicate rows, then rerank as one case."""
    records = []
    seen = set()
    attempted = expand_query(query)
    errors = []
    for term in attempted:
        try:
            rows = search_fn(term, 20)
        except Exception as exc:  # one source failure must not erase other evidence
            errors.append({"term": term, "error": str(exc)[:160]})
            continue
        for row in rows:
            key = (
                row.get("source_ref"), row.get("sheet"), row.get("row"),
                str(row.get("values", []))[:300],
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(row)
            if len(records) >= 180:
                break
        if len(records) >= 180:
            break
    evidence = rank_records(query, records, top=top)
    return {
        "schema": "personal-context/2",
        "query": query,
        "attempted_terms": attempted,
        "evidence": [asdict(item) for item in evidence],
        "source_errors": errors,
        "coverage": {
            "searched_terms": len(attempted),
            "candidate_records": len(records),
            "ranked_evidence": len(evidence),
            "complete": not errors,
        },
        "answer_policy": {
            "confirmed": "May be stated as retrieved fact with source_ref.",
            "inference": "Must be explicitly labelled as an inference.",
            "missing": "State the precise missing item; do not say the whole topic is absent.",
            "reconstruction": "Label generated replacement text as مسودة مُعاد بناؤها.",
        },
    }

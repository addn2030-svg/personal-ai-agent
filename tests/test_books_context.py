# -*- coding: utf-8 -*-
"""Regression tests for the books/learning shelf fast path.

Covers the production issue where /books replied "أمر غير معروف" because the
learning tab name did not match exactly (trailing space / diacritic) and the
search fallback filtered rows by exact tab title.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import books_context as bc  # noqa: E402

_HEADER = ["العنوان", "النوع", "المجال", "الحالة"]
_ROWS = [
    ["Essentialism — Greg McKeown", "كتاب", "الأولويات", "لم يبدأ"],
    ["Atomic Habits - James Clear", "كتاب", "بناء العادات", "لم يبدأ"],
]


def _snapshot(tab_name: str) -> dict:
    return {tab_name: [list(_HEADER)] + [list(r) for r in _ROWS]}


def test_exact_tab_name_extracts_books():
    assert len(bc.extract_books(_snapshot("المصادر والتعلم العلمي"))) == 2


def test_tab_name_variants_still_extract_books():
    for variant in [
        "المصادر والتعلم العلمي ",      # trailing space
        "المصادر والتعلّم العلمي",       # diacritic on lam
        "المصادر و التعلم العلمي",       # spaces around واو
        "مكتبة المصادر والتعلم العلمي",  # prefixed shelf word
    ]:
        assert len(bc.extract_books(_snapshot(variant))) == 2, variant


def test_operational_tabs_do_not_produce_false_books():
    # «كتابة» must not be mistaken for «كتاب»; non-learning tabs are skipped.
    data = {
        "لوحة التحكم": [["المهمة", "التصنيف", "الحالة"],
                        ["كتابة المتطلبات والنموذج الأولي", "تطوير", "قيد التنفيذ"]],
        "التطوير الشخصي": [["المجال", "النشاط"], ["الذكاء الاصطناعي", "بناء الوكلاء"]],
    }
    assert bc.extract_books(data) == []


class _FakeSheetIntelligence:
    """Mimics connectors.sheet_intelligence for the search fallback."""

    def __init__(self, results):
        self._results = results

    def search(self, query, max_results=60):
        assert query == "كتاب"
        return self._results


def test_search_fallback_matches_tab_tolerantly():
    results = [
        {"sheet": "المصادر والتعلم العلمي ", "row": 3,
         "values": ["Essentialism — Greg McKeown", "كتاب", "الأولويات", "لم يبدأ"]},
        # operational tab mentioning «كتابة» must be excluded
        {"sheet": "لوحة التحكم", "row": 33,
         "values": ["بناء الوكلاء", "كتابة المتطلبات", "تطوير"]},
    ]
    si = _FakeSheetIntelligence(results)
    books = bc._books_from_search(si, {"المصادر والتعلم العلمي ": [_HEADER] + _ROWS})
    assert [b["title"] for b in books] == ["Essentialism — Greg McKeown"]

# -*- coding: utf-8 -*-
"""Books / learning shelf reader — fixes BUG-001.

The agent said "I don't know your books list". Root cause: the books live in
the «تعلم» (Learning) tab of the master sheet, filtered by النوع == "كتاب",
but nothing injects that tab into the agent's session context.

This module reuses the ALREADY-WIRED gateway `snapshot` action (via
connectors.sheet_intelligence.snapshot) — no gateway upgrade needed. It is
read-only, deterministic, and never invents a book.

Place at: engine/books_context.py
"""
from __future__ import annotations

from typing import Any

VERSION = "v1.0"

# Tab and column names as they appear in the master sheet (verified from
# data/master-sheet.xlsx and prompts/*.md).
LEARNING_TAB = "تعلم"
BOOK_TYPE = "كتاب"

# Status priority for the suggestion (lower = suggest first).
STATUS_PRIORITY = {"جاري": 0, "جارية": 0, "لم يبدأ": 1, "متوقف": 2, "منجزة": 3, "منجز": 3}


def _find_column(header: list, *names: str) -> int:
    for i, h in enumerate(header or []):
        if str(h or "").strip() in names:
            return i
    return -1


def extract_books(snapshot_data: dict, tab_name: str = LEARNING_TAB) -> list[dict]:
    """Return the book rows from the «تعلم» tab of a gateway snapshot.

    snapshot_data shape: {tab_title: [[row...], ...]} as returned by the
    gateway `snapshot` action (first row is the header).
    """
    tab = snapshot_data.get(tab_name) or []
    if not tab:
        return []
    header = tab[0]
    idx_type = _find_column(header, "النوع", "النوع ")
    idx_title = _find_column(header, "العنوان")
    idx_goal = _find_column(header, "مرتبط بهدف", "الهدف")
    idx_status = _find_column(header, "الحالة")
    idx_applied = _find_column(header, "طُبِّق عمليًا", "طبق عمليا", "طُبّق")

    books: list[dict] = []
    for row in tab[1:]:
        row = list(row)
        def cell(i):
            if i < 0 or i >= len(row):
                return ""
            return str(row[i] or "").strip()

        kind = cell(idx_type)
        if idx_type < 0 or kind != BOOK_TYPE:
            continue
        title = cell(idx_title)
        if not title:
            continue
        books.append({
            "title": title,
            "goal": cell(idx_goal),
            "status": cell(idx_status) or "لم يبدأ",
            "applied": cell(idx_applied),
        })
    return books


def suggest_book(books: list[dict], goal: str = "") -> dict | None:
    """Deterministic pick: active first, then goal overlap, then not-started."""
    if not books:
        return None
    active = [b for b in books if STATUS_PRIORITY.get(b["status"], 9) <= 1]
    pool = active or books
    if goal:
        goal_tokens = {t for t in goal.split() if len(t) >= 3}
        scored = []
        for b in pool:
            hit = any(t in (b["goal"] + " " + b["title"]) for t in goal_tokens)
            scored.append((hit, STATUS_PRIORITY.get(b["status"], 9), b))
        scored.sort(key=lambda x: (not x[0], x[1]))
        return scored[0][2]
    # no goal: lowest status priority (active first, then not-started, etc.)
    return min(pool, key=lambda b: (STATUS_PRIORITY.get(b["status"], 9), b["title"]))


def books_context(books: list[dict]) -> str:
    """Arabic block for the agent's session context."""
    if not books:
        return ""
    lines = ["[كتبي — تبويب «تعلم»]"]
    for b in books:
        extra = f" — مرتبط بـ: {b['goal']}" if b.get("goal") else ""
        lines.append(f"- {b['title']} [{b['status']}]{extra}")
    return "\n".join(lines)


def suggest_line(books: list[dict], goal: str = "") -> str:
    """One-line Arabic suggestion (the agent reads it, never invents)."""
    b = suggest_book(books, goal)
    if not b:
        return ""
    if goal:
        return (f"اقتراح قراءة: «{b['title']}» ({b['status']}) — "
                f"مرتبط بهدفك الحالي: {b.get('goal') or 'غير محدد'}.")
    return (f"اقتراح قراءة: «{b['title']}» ({b['status']}) — "
            f"مرتبط بـ: {b.get('goal') or 'غير محدد'}.")


def live_books(max_rows: int = 60):
    """Read the live sheet through the wired gateway snapshot and return
    book rows. Returns ([books], error) — never raises."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from connectors import sheet_intelligence as si
        if not si.configured():
            return [], "gateway not configured"
        data = si.snapshot(max_rows=max_rows, max_cols=16)
        return extract_books(data), ""
    except Exception as e:  # pragma: no cover - live path
        return [], str(e)[:200]


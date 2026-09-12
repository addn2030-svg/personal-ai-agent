# -*- coding: utf-8 -*-
"""Books / learning shelf reader — fixes BUG-001.

The agent said "I don't know your books list". Root cause was twofold:
1. (FIXED) The bot's gateway URL pointed at an old `/dev` deployment that
   answered HTTP 401, so the sheet was never reachable at all.
2. (THIS FILE) The books live in a tab whose real name is
   «المصادر والتعلم العلمي» (with «مكتبة القراءة» as a second shelf and
   «تعلم» kept for backward compatibility), filtered by النوع == "كتاب".

This module reuses the ALREADY-WIRED gateway `snapshot` action (via
connectors.sheet_intelligence.snapshot) — no gateway upgrade needed. It is
read-only, deterministic, and never invents a book.

Place at: engine/books_context.py
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

VERSION = "v3.1"

# Candidate tab names, in priority order. The live sheet uses
# «المصادر والتعلم العلمي»; «مكتبة القراءة» and «تعلم» are fallbacks.
LEARNING_TABS: list[str] = ["المصادر والتعلم العلمي", "مكتبة القراءة", "تعلم"]
LEARNING_TAB = LEARNING_TABS[0]  # kept for backward compatibility
BOOK_TYPE = "كتاب"

# Status → priority (lower = suggest first).
# Exact-value groups first; substring rules handled in _status_priority.
_STATUS_IN_PROGRESS = {"جاري", "جارية", "بدأ", "بدأت", "قيد التنفيذ", "قيد القراءة"}
_STATUS_NOT_STARTED = {"لم يبدأ", "لم يبدا", "لم تبدأ", "لم تبدا"}
_STATUS_PAUSED = {"متوقف", "متوقفة", "معلق", "معلقة", "مؤجل", "مؤجلة"}
_STATUS_DONE = {"منجزة", "منجز", "مكتمل", "مكتملة", "تم", "انتهى", "انتهت"}

STATUS_PRIORITY = {
    **{s: 0 for s in _STATUS_IN_PROGRESS},
    **{s: 1 for s in _STATUS_NOT_STARTED},
    **{s: 2 for s in _STATUS_PAUSED},
    **{s: 3 for s in _STATUS_DONE},
}


def _status_priority(status: Any) -> int:
    s = str(status or "").strip()
    if s in STATUS_PRIORITY:
        return STATUS_PRIORITY[s]
    # substring fallbacks (only for unambiguous markers)
    if "جاري" in s or "تنفيذ" in s:
        return 0
    if "لم يبد" in s:
        return 1
    if "متوقف" in s or "معلق" in s or "مؤجل" in s:
        return 2
    if "منجز" in s or "مكتمل" in s or "انته" in s:
        return 3
    return 9


def _norm_tab(name: Any) -> str:
    """Normalize a tab title for tolerant matching.

    Real sheets often differ by a trailing space, tatweel/diacritic, or Arabic
    presentation-form characters. Exact equality missed «المصادر والتعلم العلمي »
    (trailing space) and silently returned zero books, so we normalize both sides.
    """
    s = str(name or "")
    s = unicodedata.normalize("NFKC", s)          # fold Arabic presentation forms
    s = re.sub(r"[ـ]", "", s)                      # tatweel
    s = re.sub(r"[ؐ-ًؚ-ٰٟۖ-ۭ]", "", s)           # diacritics/tashkeel
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Markers that identify a books/learning tab after normalization.
_LEARNING_HINTS = ("المصادر", "التعلم", "التعلّم", "القراءة", "مكتبة", "الكتب", "تعلم")


def _is_learning_tab(tab_title: str) -> bool:
    t = _norm_tab(tab_title)
    if not t:
        return False
    norm_targets = {_norm_tab(x) for x in LEARNING_TABS}
    if t in norm_targets:
        return True
    # tolerant: a title that both names the shelf (sources/reading/library) AND
    # mentions learning/reading — avoids matching unrelated operational tabs.
    has_shelf = any(h in t for h in ("المصادر", "مكتبة", "القراءة", "الكتب"))
    has_learning = any(h in t for h in ("التعلم", "التعلّم", "تعلم", "قراءة"))
    return has_shelf and has_learning


def _learning_tabs_from(snapshot_keys) -> list[str]:
    """Return the actual snapshot tab titles that look like a books/learning tab."""
    matches = [k for k in snapshot_keys if _is_learning_tab(k)]
    # canonical names first, then any others, preserving snapshot order
    canonical = [k for k in matches if _norm_tab(k) in {_norm_tab(x) for x in LEARNING_TABS}]
    others = [k for k in matches if k not in canonical]
    return canonical + others


def _find_column(header: list, *names: str) -> int:
    for i, h in enumerate(header or []):
        cell = str(h or "").strip()
        if cell in names:
            return i
    return -1


_HEADER_MARKERS = ("النوع", "العنوان", "الحالة", "الهدف", "نوع")


def _find_header_row(tab: list) -> int:
    """Locate the column-header row (some tabs start with a merged title row).

    Returns the header row index, or -1 when the tab has no recognizable
    header (data starts immediately).
    """
    for i, row in enumerate(tab[:5]):
        cells = [str(c or "").strip() for c in row]
        if any(m in cells for m in _HEADER_MARKERS):
            return i
    return -1


def _pick_status(row: list, idx_status: int) -> str:
    if 0 <= idx_status < len(row):
        s = str(row[idx_status] or "").strip()
        if s:
            return s
    # fallback: first cell that looks like a status value
    for c in row:
        s = str(c or "").strip()
        if s and _status_priority(s) < 9:
            return s
    return "لم يبدأ"


def extract_books(snapshot_data: dict, tabs: Any = None) -> list[dict]:
    """Return the book rows (النوع == كتاب) from the learning tabs.

    snapshot_data shape: {tab_title: [[row...], ...]} as returned by the
    gateway `snapshot` action (first row is usually the header).
    """
    if tabs is None:
        requested = _learning_tabs_from(snapshot_data.keys()) or LEARNING_TABS
    elif isinstance(tabs, str):
        requested = [tabs]
    else:
        requested = list(tabs)

    # Map requested names to the real snapshot keys using tolerant normalization;
    # fall back to auto-discovery if a canonical name is not present verbatim.
    real_titles: list[str] = []
    for name in requested:
        exact = snapshot_data.get(name)
        if exact is not None:
            real_titles.append(name)
        else:
            norm = _norm_tab(name)
            for key in snapshot_data.keys():
                if key not in real_titles and _norm_tab(key) == norm:
                    real_titles.append(key)
    if not real_titles and tabs is None:
        real_titles = _learning_tabs_from(snapshot_data.keys())

    books: list[dict] = []
    for tab_name in real_titles:
        tab = snapshot_data.get(tab_name) or []
        if not tab:
            continue

        header_idx = _find_header_row(tab)
        header = list(tab[header_idx]) if header_idx >= 0 else []
        idx_type = _find_column(header, "النوع", "نوع")
        idx_title = _find_column(header, "العنوان", "عنوان", "الكتاب", "المصدر", "الاسم")
        idx_goal = _find_column(header, "مرتبط بهدف", "الهدف", "المجال", "مرتبط بـ", "الغاية")
        idx_status = _find_column(header, "الحالة", "حالة", "الوضع")
        idx_notes = _find_column(header, "ملاحظات", "الخلاصة", "الفكرة الأساسية", "الاقتباس")

        for row in tab[(header_idx + 1) if header_idx >= 0 else 0:]:
            row = list(row)
            if idx_type >= 0:
                kind = str(row[idx_type] or "").strip() if idx_type < len(row) else ""
                if kind != BOOK_TYPE:
                    continue
            else:
                # no «النوع» header: accept only rows with an exact «كتاب» cell
                if BOOK_TYPE not in [str(c or "").strip() for c in row]:
                    continue

            def cell(i: int) -> str:
                if i < 0 or i >= len(row):
                    return ""
                return str(row[i] or "").strip()

            title = cell(idx_title) if idx_title >= 0 else ""
            if not title:
                title = next((c for c in (str(x or "").strip() for x in row) if c), "").strip()
            if not title or title == BOOK_TYPE:
                continue

            books.append({
                "title": title,
                "goal": cell(idx_goal),
                "status": _pick_status(row, idx_status),
                "notes": cell(idx_notes),
                "tab": tab_name,
            })
    return books


def suggest_book(books: list[dict], goal: str = "") -> dict | None:
    """Deterministic pick: status priority, then title; goal overlap wins."""
    if not books:
        return None

    def key(b: dict):
        return (_status_priority(b["status"]), b["title"])

    ranked = sorted(books, key=key)
    if goal:
        tokens = {t for t in goal.split() if len(t) >= 3}
        overlap = [b for b in ranked
                   if any(t in (b["goal"] + " " + b["title"]) for t in tokens)]
        if overlap:
            return min(overlap, key=key)
    return ranked[0]


def books_context(books: list[dict]) -> str:
    """Arabic block for the agent's session context."""
    if not books:
        return ""
    lines = [
        "[قائمة كتبي الحقيقية — قُرئت الآن مباشرة من شيت «المصادر والتعلم» وهي متاحة لك؛ "
        "لا تقل إن الشيت غير متاح]"
    ]
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
    """Read the live sheet through the wired gateway and return book rows.

    Strategy (belt and suspenders — both routes are proven in production):
      1. snapshot + column-aware extract_books (fast, structured);
      2. if that yields nothing, fall back to the gateway `search` action for
         «كتاب» — the exact mechanism that makes `/find كتاب` work in the bot —
         so header-name differences can never hide the books again.
    Returns ([books], error) — never raises.
    """
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from connectors import sheet_intelligence as si
        if not si.configured():
            print(f"[books_context v{VERSION}] gateway not configured", flush=True)
            return [], "gateway not configured"
        data = si.snapshot(max_rows=max_rows, max_cols=16)
        books: list[dict] = []
        extract_error = ""
        try:
            books = extract_books(data)
        except Exception as exc:  # never let structured extraction skip the fallback
            extract_error = f"{type(exc).__name__}: {str(exc)[:120]}"
        if not books:
            try:
                books = _books_from_search(si, data)
            except Exception as exc:
                if not extract_error:
                    extract_error = f"search: {type(exc).__name__}: {str(exc)[:120]}"
        print(
            f"[books_context v{VERSION}] live_books -> {len(books)} book(s) "
            f"(tabs_checked={len(_learning_tabs_from(data.keys()))}"
            f"{', extract_error=' + extract_error if extract_error else ''})",
            flush=True,
        )
        if not books:
            return [], (extract_error or "no book rows found in learning tabs")
        return books, ""
    except Exception as e:  # pragma: no cover - live path
        print(f"[books_context v{VERSION}] live_books error: {str(e)[:160]}", flush=True)
        return [], str(e)[:200]


def _books_from_search(si, data=None, max_results=60) -> list[dict]:
    """Rebuild the books list from the gateway `search` action (proven path).

    Each result row looks like the `/find كتاب` output, e.g.
    ["Essentialism — Greg McKeown", "كتاب", "الأولويات", ..., "لم يبدأ", ...].
    Tab membership is matched tolerantly (a trailing space/diacritic must not
    hide a row), and auto-discovered learning tabs are accepted when `data`
    (the snapshot dict) is supplied.
    """
    snapshot_keys = list((data or {}).keys())
    learning = set(LEARNING_TABS) | set(_learning_tabs_from(snapshot_keys))
    norm_learning = {_norm_tab(t) for t in learning}
    try:
        results = si.search("كتاب", max_results)
    except Exception:
        return []

    books: list[dict] = []
    seen_titles: set[str] = set()
    for r in results:
        sheet = str(r.get("sheet") or "")
        in_learning = _norm_tab(sheet) in norm_learning or _is_learning_tab(sheet)
        if not in_learning:
            continue
        values = [str(v or "").strip() for v in r.get("values", [])]
        if "كتاب" not in values:
            continue

        # title = the cell right before «كتاب», else the first real cell
        bi = values.index("كتاب")
        if bi > 0 and values[bi - 1]:
            title = values[bi - 1]
        else:
            title = next((v for v in values if v and v != "كتاب"), "")
        if not title or title in seen_titles:
            continue

        # status = first cell that looks like a status value
        status = "لم يبدأ"
        for v in values:
            if _status_priority(v) < 9:
                status = v
                break

        # goal = first remaining informative cell
        goal = next(
            (v for v in values if v and v not in (title, status, "كتاب")),
            "",
        )

        seen_titles.add(title)
        books.append({
            "title": title,
            "goal": goal,
            "status": status,
            "notes": "",
            "tab": r.get("sheet"),
        })
    return books

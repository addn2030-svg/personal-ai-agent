# -*- coding: utf-8 -*-
"""Deterministic mapping of bare numbered replies to previously presented options.

BUG-002 fix ("ماذا تقصد بـ 11؟"): when the agent presents numbered choices and the
user replies with a bare digit, the reply must be mapped to the matching option —
never merged with another digit and never treated as a brand-new question.

This module is deterministic: no model call, and a single tightly-anchored pattern
per direction. Its output is evidence injected into the model context, not an
autonomous action; execution still follows the normal approval paths.
"""
from __future__ import annotations

import re

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Bare menu reply: "1", "٢", "1.", "2)", "الخيار 2", "رقم ١", "اختر 3",
# "option 2", "choice 2". Deliberately capped at two digits so sentences,
# years, and identifiers never match.
_BARE_NUMBER_RE = re.compile(
    r"^\s*(?:(?:الخيار|الاختيار|رقم|اختر|اختار|أختار|option|choice)\s*#?\s*)?"
    r"#?\s*([0-9]{1,2}|[٠-٩]{1,2})\s*[).:\-،,]?\s*$",
    re.I,
)

# An option line as models commonly render menus: "1) نص", "1. نص", "1- نص",
# "1: نص", "1]" and the same with Arabic-Indic digits, optionally bulleted.
_OPTION_LINE_RE = re.compile(
    r"^\s*[-•*–—]?\s*#?\s*([0-9]{1,2}|[٠-٩]{1,2})\s*[).:\-]\s*(\S.*)$"
)

MIN_OPTIONS = 2
MAX_OPTION_NUMBER = 12


def normalize_digits(value: str) -> str:
    """Arabic-Indic digits -> ASCII digits; everything else unchanged."""
    return str(value or "").translate(_ARABIC_INDIC)


def parse_numbered_options(text: str) -> dict:
    """Return {number: option_text} for a numbered menu, or {} if it is not one.

    A valid menu needs at least MIN_OPTIONS entries and must include option 1.
    That keeps numbered section headings inside long documents from silently
    becoming answerable menus.
    """
    options = {}
    for line in (text or "").splitlines():
        match = _OPTION_LINE_RE.match(line)
        if not match:
            continue
        number = int(normalize_digits(match.group(1)))
        if not 1 <= number <= MAX_OPTION_NUMBER:
            continue
        options.setdefault(number, match.group(2).strip()[:300])
    if len(options) < MIN_OPTIONS or 1 not in options:
        return {}
    return options


def parse_bare_number(text: str):
    """Return the int of a bare menu reply, or None when it is not one."""
    match = _BARE_NUMBER_RE.match((text or "").strip())
    if not match:
        return None
    number = int(normalize_digits(match.group(1)))
    if not 1 <= number <= MAX_OPTION_NUMBER:
        return None
    return number


def resolve_numbered_reply(text: str, recent_rows: list):
    """Map a bare numbered reply onto options in the most recent assistant message.

    Only the most recent assistant message is considered: fishing through older
    menus is exactly how mis-mapping happens. Returns
    {"number", "option_text", "source_excerpt"} or None.
    """
    number = parse_bare_number(text)
    if number is None:
        return None
    for row in reversed(recent_rows or []):
        if str(row.get("role")) != "assistant":
            continue
        content = str(row.get("content") or "")
        options = parse_numbered_options(content)
        if not options:
            return None
        option_text = options.get(number)
        if option_text is None:
            return None
        return {
            "number": number,
            "option_text": option_text,
            "source_excerpt": content[:500],
        }
    return None


def resolution_context_block(hit: dict) -> str:
    """Evidence block injected into the model context for a resolved menu reply."""
    return (
        "NUMBERED_REPLY_RESOLUTION (deterministic, computed in code — not a guess):\n"
        f"The user's latest message is the menu reply \"{hit['number']}\". In code it was "
        "matched against the numbered options you presented in your immediately previous "
        f"message. It selects exactly this option: \"{hit['option_text']}\".\n"
        "Treat that option as the user's explicit selection. Act on it (produce the "
        "confirmation, decision, or draft it asks for); never ask what the number means, "
        "never merge or reinterpret digits, and never re-present the same menu. If acting "
        "on the option requires approval, follow the normal proposal -> approval path."
    )

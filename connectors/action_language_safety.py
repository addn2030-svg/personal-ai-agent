# -*- coding: utf-8 -*-
"""Small language-safety overlay for Natural Action Executor.

Explicit negation must outrank keyword detection. For example, `لا يوجد تذكير`
must never be interpreted as `create a default reminder` merely because it contains
the word `تذكير`.
"""
from __future__ import annotations

import re

from connectors import action_deadline_report as deadline_report

_INSTALLED = False
_ORIGINAL = None
_NEGATED_REMINDER = re.compile(
    r"لا\s+(?:يوجد|أريد|اريد)\s+(?:أي\s+)?تذكير|"
    r"بدون\s+تذكير|من\s+دون\s+تذكير|no\s+reminder|do\s+not\s+remind|don't\s+remind",
    re.I,
)


def install():
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    _ORIGINAL = deadline_report._parse_reminder_minutes

    def safe_parse(text: str, *, deadline_present: bool):
        if _NEGATED_REMINDER.search(text or ""):
            return None
        return _ORIGINAL(text, deadline_present=deadline_present)

    deadline_report._parse_reminder_minutes = safe_parse
    _INSTALLED = True

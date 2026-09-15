#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 اختبار تحميل التبويبات التلقائي من Google Sheets
Tests the auto-load pipeline for the new tabs:
  التطوير الشخصي, مكتبة العبارات التوجيهية, الهوية الشخصية, 📥 مراجعة اليوم — Inbox

التشغيل:
  python3 scripts/test_sheets_auto_load.py              ← كل الاختبارات
  python3 scripts/test_sheets_auto_load.py --offline     ← فقط اختبارات بدون اتصال
  python3 scripts/test_sheets_auto_load.py --live        ← فقط اختبارات حية (تتطلب اتصال Google)
  python3 scripts/test_sheets_auto_load.py --probe       ← فحص مباشر لسياق العمليات
  python3 scripts/test_sheets_auto_load.py --probe "ما أهم مهامي غداً؟"
"""
from __future__ import annotations

import json
import os
import sys
import textwrap

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"
INFO = "ℹ️"

NEW_TABS = [
    "التطوير الشخصي",
    "مكتبة العبارات التوجيهية",
    "الهوية الشخصية",
    "📥 مراجعة اليوم — Inbox",
]

# ─── helpers ────────────────────────────────────────────────────────────────
def _header(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")

def _ok(msg):
    print(f"  {PASS} {msg}")

def _fail(msg):
    print(f"  {FAIL} {msg}")

def _skip(msg):
    print(f"  {SKIP} {msg}")

def _info(msg):
    print(f"  {INFO} {msg}")


# ─── 1. offline: code-level assertions ─────────────────────────────────────
def test_offline_tab_lists():
    """Verify all new tabs are present in the three code-level lists."""
    _header("1) قوائم التبويبات في الكود (بدون اتصال)")
    from connectors import ops_context, sheet_intelligence

    all_ok = True

    # ops_context.OPS_SHEET_TABS (session context)
    for tab in NEW_TABS:
        if tab in ops_context.OPS_SHEET_TABS:
            _ok(f"OPS_SHEET_TABS contains: {tab}")
        else:
            _fail(f"OPS_SHEET_TABS MISSING: {tab}")
            all_ok = False

    # sheet_intelligence.PRIORITY_TABS (snapshot ordering)
    for tab in NEW_TABS:
        if tab in sheet_intelligence.PRIORITY_TABS:
            _ok(f"PRIORITY_TABS contains: {tab}")
        else:
            _fail(f"PRIORITY_TABS MISSING: {tab}")
            all_ok = False

    return all_ok


def test_offline_context_limit():
    """Verify the context limit was raised."""
    _header("2) حد السياق (OPS_CONTEXT_LIMIT)")
    from connectors import ops_context

    limit = ops_context.OPS_CONTEXT_LIMIT
    if limit >= 4000:
        _ok(f"OPS_CONTEXT_LIMIT = {limit} chars (≥ 4000)")
        return True
    else:
        _fail(f"OPS_CONTEXT_LIMIT = {limit} chars (expected ≥ 4000)")
        return False


def test_offline_sheet_lines_flow():
    """Mock a snapshot with new tab data and verify it flows through _sheet_lines()."""
    _header("3) تدفق البيانات عبر _sheet_lines() (mock)")
    from unittest.mock import patch
    from connectors import ops_context, sheet_intelligence

    snapshot = {
        "Projects": [["AI Agent", "Active"]],
        "التطوير الشخصي": [["قراءة كتاب الأسبوع", "في التقدم"]],
        "مكتبة العبارات التوجيهية": [["كن قوياً", "La ilaha illallah"]],
        "الهوية الشخصية": [["الاسم عبدالرحمن", "مطور أنظمة"]],
        "📥 مراجعة اليوم — Inbox": [["مراجعة البريف", "لم يبدأ"]],
    }
    with patch.object(sheet_intelligence, "configured", return_value=True), \
         patch.object(sheet_intelligence, "snapshot", return_value=snapshot):
        lines = ops_context._sheet_lines()

    if not lines:
        _fail("_sheet_lines() returned empty")
        return False

    joined = "\n".join(lines)
    found, missing = [], []
    for tab in NEW_TABS:
        if tab in joined:
            found.append(tab)
        else:
            missing.append(tab)

    for t in found:
        _ok(f"Data from «{t}» appeared in context capsule")
    for t in missing:
        _fail(f"Data from «{t}» did NOT appear in context capsule")

    _info(f"Total context lines: {len(lines)}")
    _info(f"Sample output:")
    for line in lines[:6]:
        print(f"       {line}")
    if len(lines) > 6:
        print(f"       ... ({len(lines) - 6} more)")

    return not missing


def test_offline_trigger_regex():
    """Verify operational queries trigger ops context (existing trigger regex scope)."""
    _header("4) تفعيل سياق العمليات (trigger regex)")
    from connectors import ops_context

    queries = [
        ("ما هي أولويات غدا؟", True),
        ("ما أهم مهامي وأهداف التطوير الشخصي؟", True),
        ("Give me priorities tomorrow", True),
        ("What tasks are pending today?", True),
        ("Explain quantum computing", False),
        ("hello how are you", False),
    ]
    all_ok = True
    for query, expected in queries:
        result = ops_context.needs_ops_context(query)
        if result == expected:
            _ok(f"«{query[:40]}» → triggered={result}")
        else:
            _fail(f"«{query[:40]}» → triggered={result} (expected {expected})")
            all_ok = False
    return all_ok


# ─── 2. live: real Google Sheets API ───────────────────────────────────────
def test_live_snapshot():
    """Read the actual Google Sheets workbook and verify new tabs exist."""
    _header("5) قراءة حية من Google Sheets (snapshot)")
    from connectors import sheet_intelligence

    if not sheet_intelligence.configured():
        _skip("Google Sheets غير مُهيّأ — تخطّي (ضبط GOOGLE_SHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON)")
        return None

    try:
        data = sheet_intelligence.snapshot(max_rows=20, max_cols=8)
    except Exception as e:
        _fail(f"Snapshot failed: {e}")
        return False

    if not data:
        _fail("Snapshot returned empty data")
        return False

    found_tabs = set(data.keys())
    _info(f"Total tabs read: {len(found_tabs)}")
    _info(f"Tabs: {', '.join(sorted(found_tabs)[:15])}{'...' if len(found_tabs) > 15 else ''}")

    all_ok = True
    for tab in NEW_TABS:
        if tab in data:
            rows = data[tab]
            if rows:
                _ok(f"«{tab}» → {len(rows)} rows")
            else:
                _ok(f"«{tab}» → present but empty")
        else:
            _fail(f"«{tab}» NOT found in workbook")
            all_ok = False

    return all_ok


def test_live_ops_context():
    """Build the full ops context packet with a real sheet read."""
    _header("6) بناء سياق العمليات الكامل (build_ops_context)")
    from connectors import ops_context

    try:
        packet = ops_context.build_ops_context("ما أهم أولوياتي وأهدافي الشخصية؟")
    except Exception as e:
        _fail(f"build_ops_context failed: {e}")
        return False

    if not packet.triggered:
        _fail("Packet not triggered (regex mismatch)")
        return False

    _ok(f"Triggered: {packet.triggered}")
    _ok(f"Sources: {packet.sources}")
    _ok(f"Calendar rows: {packet.calendar_count}")
    _ok(f"Sheet rows: {packet.sheet_count}")
    _ok(f"Context chars: {len(packet.text)} / {ops_context.OPS_CONTEXT_LIMIT}")

    if packet.errors:
        for err in packet.errors:
            _info(f"Error: {err[:200]}")

    # check if new tab names appear in the context text
    new_tab_refs = [t for t in NEW_TABS if t in packet.text]
    if new_tab_refs:
        _ok(f"New tabs found in context text: {', '.join(new_tab_refs)}")
    else:
        _info("No new tab names in context text (tabs may be empty or sheets unavailable)")

    if packet.text:
        print(f"\n{'─' * 40}")
        print("  📋 معاينة السياق (أول 800 حرف):")
        print(f"{'─' * 40}")
        print(textwrap.indent(packet.text[:800], "  "))
    else:
        _info("Context text is empty (sheets may be unavailable)")

    return True


# ─── 3. ops_context.probe (zero-model diagnostic) ──────────────────────────
def test_live_probe(goal=None):
    """Run the zero-model probe to see exactly what the context would look like."""
    _header("7) تشخيص سياق العمليات (probe — بدون نموذج)")
    from connectors import ops_context

    goal = goal or "ما أهم مهامي وأهداف التطوير الشخصي غداً؟"
    _info(f"Goal: «{goal}»")

    try:
        result = ops_context.probe(goal)
    except Exception as e:
        _fail(f"Probe failed: {e}")
        return False

    _ok(f"Triggered: {result['triggered']}")
    _ok(f"Sources: {result['sources']}")
    _ok(f"Calendar rows: {result['calendar_rows']}")
    _ok(f"Sheet rows: {result['sheet_rows']}")
    _ok(f"Chars: {result['chars']}")

    if result["errors"]:
        for err in result["errors"]:
            _info(f"Error: {err[:200]}")

    if result["preview"]:
        print(f"\n{'─' * 40}")
        print("  📋 Preview:")
        print(f"{'─' * 40}")
        print(textwrap.indent(result["preview"], "  "))
    else:
        _info("Preview is empty")

    return True


# ─── 4. telegram brief snapshot (live) ─────────────────────────────────────
def test_live_brief_snapshot():
    """Read the direct brief snapshot used by /brief command."""
    _header("8) معاينة بريف التيليجرام (Direct Brief snapshot)")
    try:
        from connectors.telegram_webhook_runtime import _direct_brief_snapshot, _direct_ready
    except ImportError:
        _skip("telegram_webhook_runtime not importable")
        return None

    if not _direct_ready():
        _skip("Direct Sheets route not ready (missing SHEET_ID or SERVICE_ACCOUNT)")
        return None

    try:
        data = _direct_brief_snapshot(max_rows=20, max_cols=8)
    except Exception as e:
        _fail(f"Direct Brief snapshot failed: {e}")
        return False

    found_tabs = set(data.keys())
    _info(f"Tabs read: {len(found_tabs)}")

    for tab in NEW_TABS:
        if tab in data:
            _ok(f"«{tab}» → {len(data[tab])} rows in brief snapshot")
        else:
            _fail(f"«{tab}» NOT in brief snapshot")

    return True


# ─── main ───────────────────────────────────────────────────────────────────
def main():
    args = set(sys.argv[1:])
    offline_only = "--offline" in args
    live_only = "--live" in args
    probe_only = "--probe" in args
    probe_goal = None
    for a in sys.argv[1:]:
        if a.startswith("--probe") or a.startswith("--goal"):
            continue
        if not a.startswith("--"):
            probe_goal = a
            break

    print("🧪 اختبار تحميل التبويبات التلقائي من Google Sheets")
    print("=" * 60)

    if probe_only:
        test_live_probe(probe_goal)
        return

    results = {}
    if not live_only:
        results["tab_lists"]        = test_offline_tab_lists()
        results["context_limit"]    = test_offline_context_limit()
        results["sheet_lines_flow"] = test_offline_sheet_lines_flow()
        results["trigger_regex"]    = test_offline_trigger_regex()

    if not offline_only:
        results["live_snapshot"]    = test_live_snapshot()
        results["live_ops_context"] = test_live_ops_context()
        results["live_probe"]       = test_live_probe(probe_goal)
        results["brief_snapshot"]   = test_live_brief_snapshot()

    # summary
    _header("📊 ملخص النتائج")
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)

    for name, ok in results.items():
        icon = PASS if ok is True else (FAIL if ok is False else SKIP)
        print(f"  {icon} {name}")

    print(f"\n  الإجمالي: {passed} نجح / {failed} فشل / {skipped} تخطّي من {total}")

    if failed:
        print(f"\n{FAIL} هناك اختبارات فاشلة — راجع الأخطاء أعلاه.")
        raise SystemExit(1)
    elif skipped and not passed:
        print(f"\n{SKIP} كل الاختبارات الحيّة تُخطّيت — تأكد من ضبط GOOGLE_SHEET_ID و GOOGLE_SERVICE_ACCOUNT_JSON.")
    else:
        print(f"\n{PASS} كل الاختبارات نجحت.")


if __name__ == "__main__":
    main()

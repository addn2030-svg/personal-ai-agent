# -*- coding: utf-8 -*-
"""Deterministic pre-brief discovery for connected rehabilitation sheets."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

DATA_DIR = Path(os.environ.get("AI_OS_DATA_DIR", "/tmp/abdulrahman-ai-os"))
SNAPSHOT_FILE = DATA_DIR / "brief-sheet-snapshot.json"
DATE_RX = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")


def _row_key(tab, index, row):
    text = " | ".join(str(x).strip() for x in row)
    return hashlib.sha256(f"{tab}:{index}:{text}".encode("utf-8")).hexdigest()[:16]


def normalize_snapshot(data):
    rows = {}
    for tab, values in (data or {}).items():
        for index, row in enumerate(values[1:], 2):
            if not any(str(x).strip() for x in row):
                continue
            rows[_row_key(tab, index, row)] = {
                "sheet": tab, "row": index,
                "values": [str(x) for x in row],
            }
    return rows


def load_previous():
    try:
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"rows": {}, "generated_at": ""}


def save_snapshot(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "rows": rows}
    tmp = SNAPSHOT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SNAPSHOT_FILE)


def _dated_items(rows, today, days=14):
    result = []
    end = today + dt.timedelta(days=days)
    for item in rows.values():
        text = " | ".join(item["values"])
        for y, m, d in DATE_RX.findall(text):
            try:
                value = dt.date(int(y), int(m), int(d))
            except ValueError:
                continue
            if today <= value <= end:
                result.append({**item, "date": value.isoformat()})
                break
    return result[:20]


def _flagged(rows, pattern, limit=20):
    rx = re.compile(pattern, re.I)
    return [item for item in rows.values()
            if rx.search(" | ".join(item["values"]))][:limit]


def discover(data, today=None, persist=True):
    today = today or dt.date.today()
    current = normalize_snapshot(data)
    previous_payload = load_previous()
    previous = previous_payload.get("rows", {})
    changed = [v for k, v in current.items() if k not in previous][:30]
    removed = [v for k, v in previous.items() if k not in current][:20]
    report = {
        "snapshot_previous_at": previous_payload.get("generated_at", ""),
        "snapshot_current_at": dt.datetime.now().isoformat(timespec="seconds"),
        "new_or_changed": changed,
        "removed_or_resolved": removed,
        "upcoming_dates": _dated_items(current, today),
        "missing_or_incomplete": _flagged(current, r"ناقص|غير مكتمل|بدون مالك|بدون موعد|pending|missing|incomplete"),
        "blockers_and_risks": _flagged(current, r"تعثر|عائق|مخاطر|متأخر|عاجل|block|risk|overdue"),
        "decisions_required": _flagged(current, r"قرار مطلوب|يحتاج قرار|موافقة|اعتماد|decision|required approval"),
        "important_information": _flagged(current, r"معلومة مهمة|فرصة|نمط متكرر|تحسين|سلامة|opportunity|important|safety"),
        "stats": {"rows": len(current), "new_or_changed": len(changed), "removed_or_resolved": len(removed)},
    }
    if persist:
        save_snapshot(current)
    return report


def compact_discovery(report, limit=12000):
    return json.dumps(report, ensure_ascii=False, separators=(",", ":"))[:limit]

# -*- coding: utf-8 -*-
"""
ترحيل لمرة واحدة: master-sheet.xlsx → data/state.json
(الشيت يبقى صيغة استيراد/تصدير؛ المخزن الحقيقي الموحد هو state.json — إصلاح C1)
التشغيل:        python3 engine/migrate.py
إعادة الترحيل:  python3 engine/migrate.py --force
"""
import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openpyxl import load_workbook
from store import Store, log_event

SHEET = os.path.join(BASE, "data", "master-sheet.xlsx")

TAB_MAP = {
    "مهام": "tasks", "مشاريع": "projects", "عملاء وفرص": "leads",
    "مؤشرات القسم": "kpis", "مواعيد": "meetings", "قرارات": "decisions",
    "متابعة مرضى": "followups", "صندوق الصوت": "voice", "تعلم": "learning",
    "مالية": "finance",
}

if os.path.exists(Store().path) and "--force" not in sys.argv:
    print("state.json موجود أصلًا. لإعادة الترحيل استخدم:  python3 engine/migrate.py --force")
    raise SystemExit(0)

wb = load_workbook(SHEET, data_only=True)
state = {"meta": {}, "waiting_for": [], "action_queue": []}

def rows_of(tab):
    ws = wb[tab]
    hdrs = [c.value for c in ws[1]]
    out = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if all(v is None for v in r):
            continue
        row = {}
        for h, v in zip(hdrs, r):
            if isinstance(v, dt.datetime):
                v = v.date() if (v.hour == v.minute == v.second == 0) else v
            row[h] = v
        out.append(row)
    return out

for tab, key in TAB_MAP.items():
    state[key] = rows_of(tab)

# ---- اشتقاق waiting_for (المتابعات المفتوحة) من العملاء والمشاريع ----
for l in state["leads"]:
    if l.get("الحالة") == "انتظار رد":
        state["waiting_for"].append({
            "item": f"رد من {l['الجهة']} بشأن {l.get('الخدمة', '')}".strip(),
            "source": "عملاء وفرص", "expected_from": l["الجهة"],
            "since": l.get("آخر تواصل"), "follow_up_date": None})
for p in state["projects"]:
    if p.get("الحالة") == "انتظار":
        state["waiting_for"].append({
            "item": f"تحرّك في مشروع {p['المشروع']} ({p.get('الخطوة التالية', '')})".strip(),
            "source": "مشاريع", "expected_from": "داخلي",
            "since": p.get("آخر تقدم"), "follow_up_date": None})

store = Store()
store.commit(state, "migrate_from_sheet",
             rows={k: len(v) for k, v in state.items() if isinstance(v, list)})
log_event("migrate_done", source="master-sheet.xlsx")

total = sum(len(state[k]) for k in TAB_MAP.values())
print(f"✅ رُحّل الشيت إلى data/state.json — {total} صفًا في 10 أقسام + "
      f"{len(state['waiting_for'])} عنصر انتظار مُشتق.")
print("   الشيت يبقى صيغة استيراد/تصدير؛ المخزن الحقيقي الموحد الآن state.json (قاعدة الكاتب الواحد).")

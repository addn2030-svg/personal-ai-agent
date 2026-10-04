# -*- coding: utf-8 -*-
"""
أداة ترحيل بيانات النظام القديم إلى مستوى Level 2 — تشغيل واحد.

    python3 -m level2.migrate                      # من data/state.json القديم (إن وجد)
    python3 -m level2.migrate --sheet "ملف.xlsx"   # من ملف Google Sheets المُصدَّر (backup)

يستورد: المهام المفتوحة · عناصر الانتظار · القرارات غير المحسومة.
لا يحذف ولا يعدل المصدر — قراءة فقط. التكرار آمن (idempotent بالعنوان).
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from level2.state import get_store, now  # noqa: E402

ROOT = os.path.dirname(BASE_DIR)
LEGACY_STATE = os.path.join(ROOT, "data", "state.json")


def _norm(title: str) -> str:
    return " ".join((title or "").split()).strip().lower()


def from_legacy_state(store) -> int:
    """من data/state.json (نظام v0.x): مهام مفتوحة + انتظار + قرارات."""
    if not os.path.exists(LEGACY_STATE):
        return 0
    import json
    with open(LEGACY_STATE, "r", encoding="utf-8") as f:
        legacy = json.load(f)

    existing = {_norm(t.get("title", "")) for t in store.snapshot()["tasks"]}
    imported = 0

    for t in legacy.get("tasks", []):
        title = (t.get("title") or "").strip()
        status = (t.get("status") or "").lower()
        if not title or _norm(title) in existing:
            continue
        if status in ("done", "مكتمل", "مكتملة", "منجزة", "ملغى", "cancelled"):
            continue
        store.add_task(
            title=title,
            area=t.get("area") or t.get("domain") or "شخصي",
            due=t.get("due") or t.get("due_date"),
            next_step=t.get("next_step"),
        )
        existing.add(_norm(title))
        imported += 1

    for w in legacy.get("waiting_for", []):
        item = (w.get("item") or w.get("title") or "").strip()
        if not item:
            continue
        store.add_waiting(item=item, who=w.get("waiting_on") or w.get("who") or "غير محدد")

    for d in legacy.get("decisions", []):
        title = (d.get("title") or d.get("decision") or "").strip()
        if not title or d.get("status") == "محسوم":
            continue
        store.add_decision(title=title, option=d.get("option"))

    return imported


def from_sheet_xlsx(store, path: str) -> int:
    """من ملف الشيت المُصدَّر: خطة الإنجاز والمهام + Waiting_For + القرارات."""
    if not os.path.exists(path):
        print(f"لم أجد الملف: {path}")
        return 0
    import shutil
    import tempfile
    import openpyxl  # اختياري — موجود في requirements.txt للمستودع
    # ملفات تصدير Google Sheets قد تكون بلا امتداد — openpyxl يشترط .xlsx
    if not path.lower().endswith((".xlsx", ".xlsm")):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.close()
        shutil.copyfile(path, tmp.name)
        path = tmp.name
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    finally:
        try:
            if "tmp" in locals():
                os.unlink(tmp.name)
        except OSError:
            pass

    existing = {_norm(t.get("title", "")) for t in store.snapshot()["tasks"]}
    imported = 0

    # خطة الإنجاز والمهام — العمود A العنوان، K الحالة، L الاستحقاق، M الخطوة التالية
    if "خطة الإنجاز والمهام" in wb.sheetnames:
        ws = wb["خطة الإنجاز والمهام"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            title = str(row[0]).strip()
            status = str(row[10] or "").strip()
            if _norm(title) in existing:
                continue
            if status in ("مكتمل", "ملغى"):
                continue
            due = row[11]
            due = str(due)[:10] if due else None
            store.add_task(title=title, next_step=str(row[12]) if row[12] else None, due=due)
            existing.add(_norm(title))
            imported += 1

    # Waiting_For — B العنصر، C بانتظار من
    if "Waiting_For" in wb.sheetnames:
        ws = wb["Waiting_For"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[1]:
                continue
            item = str(row[1]).strip()
            if item:
                store.add_waiting(item=item, who=str(row[2] or "غير محدد").strip())

    # القرارات — C القرار، G الحالة
    if "القرارات" in wb.sheetnames:
        ws = wb["القرارات"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[2]:
                continue
            title = str(row[2]).strip()
            status = str(row[6] or "").strip()
            if title and status != "محسوم":
                store.add_decision(title=title, option=str(row[3]) if row[3] else None)

    return imported


def main() -> None:
    store = get_store()
    print(f"الهدف: {store.path}")

    n1 = from_legacy_state(store)
    print(f"✓ من النظام القديم: {n1} مهمة")

    sheet = None
    for arg in sys.argv[1:]:
        if arg == "--sheet":
            continue
        if not arg.startswith("--"):
            sheet = arg
    if sheet is None:
        # ابحث عن نسخة الشيت المصدرة تلقائيًا في مجلد المستودع
        for cand in (os.path.join(ROOT, "google_drive"), ROOT):
            if os.path.isdir(cand):
                for f in sorted(os.listdir(cand)):
                    low = f.lower()
                    if ("خط" in f or "master" in low or "sheet" in low) and not f.startswith("."):
                        sheet = os.path.join(cand, f)
                        break
            if sheet:
                break
    if sheet:
        print(f"↧ من الشيت: {sheet}")
        n2 = from_sheet_xlsx(store, sheet)
        print(f"✓ من الشيت: {n2} مهمة")

    b = store.brief()
    print(
        f"\nالنتيجة: مهام مفتوحة {b['tasks_open']} · متأخرة {b['tasks_overdue']} · "
        f"قرارات معلقة {b['decisions_pending']} · انتظار {b['waiting_open']}"
    )


if __name__ == "__main__":
    main()

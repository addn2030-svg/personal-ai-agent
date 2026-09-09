# -*- coding: utf-8 -*-
"""
أداة شجرة مجلدات Google Drive — Master OS.

المصدر الحقيقة التصميمي هو engine/master_os.py (MASTER_TREE). هذا الملف:
  1) يولّد تقرير الشجرة النصي: reports/master-os-drive-tree.md (جاهز للصق
     أو للنسخ إلى أي محرر نصوص/مستند).
  2) يولّد قائمة إنشاء (Checklist) بأسماء المجلدات والملفات المطلوب إنشاؤها
     على Google Drive — بالترتيب نفسه من الجذر.
  3) يزامن صورة الشجرة في قسم drive_tree بمخزن الحالة (مثل نمط asset_registry).

التشغيل:
  python3 engine/drive_tree.py render      ← التقرير + المزامنة
  python3 engine/drive_tree.py checklist   ← قائمة الإنشاء (بدون أي بيانات حية)

الأمان: أداة محلية بحتة — لا تستدعي Drive API ولا تكشف أي بيانات مستخدم.
إنشاء المجلدات الفعلي يتم يدويًا (أو عبر موصل Google Drive بصلاحية الكتابة
خلف بوابة الاعتماد مستقبلًا).
"""
from __future__ import annotations

import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from master_os import MASTER_TREE, FOLDER_EMOJI, DOC_EMOJI, SHEET_EMOJI, tree_spec, _tree_digest
from store import Store, log_event

REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

TYPE_ICON = {"folder": FOLDER_EMOJI, "doc": DOC_EMOJI, "sheet": SHEET_EMOJI}
TYPE_AR = {"folder": "مجلد فرعي", "doc": "مستند", "sheet": "جدول بيانات"}


def folder_paths():
    """قائمة مسارات المجلدات التي يجب إنشاؤها (من الجذر)."""
    paths = [("Abdulrahman_Master_OS", "الجذر — نظام التشغيل الشخصي")]
    for f in MASTER_TREE:
        paths.append((f"Abdulrahman_Master_OS/{f['name']}", f["purpose"]))
        for (kind, name, _p) in f["children"]:
            if kind == "folder":
                paths.append((f"Abdulrahman_Master_OS/{f['name']}/{name}", "مجلد معرفي"))
    return paths


def _tree_text():
    lines = ["# 📁 Abdulrahman_Master_OS — شجرة مجلدات Google Drive",
             "",
             "> مرجع معماري v0.9 — يُستخدم كخريطة إنشاء للمجلدات والملفات على",
             "> Google Drive، وكمصدر تغذية منظم للوكلاء الفرعيين.",
             "",
             "```text",
             "Abdulrahman_Master_OS/",
             "│",
             ]
    for i, f in enumerate(MASTER_TREE):
        is_last = i == len(MASTER_TREE) - 1
        prefix = "└──" if is_last else "├──"
        lines.append(f"{prefix} 📂 {f['name']}/                 ({f['purpose']})")
        n = len(f["children"])
        for j, (kind, name, purpose) in enumerate(f["children"]):
            if kind == "folder":
                branch = "    " if is_last else "│   "
                lines.append(f"{branch}{'└──' if j == n - 1 else '├──'} 📂 {name}/   ({purpose})")
            else:
                branch = "    " if is_last else "│   "
                icon = SHEET_EMOJI if kind == "sheet" else DOC_EMOJI
                lines.append(f"{branch}{'└──' if j == n - 1 else '├──'} {icon} {name}   ({purpose})")
    lines += ["```", "",
              "## ✅ قائمة الإنشاء على Google Drive (بالترتيب من الجذر)",
              ""]
    for path, purpose in folder_paths():
        lines.append(f"- [ ] `{path}` — {purpose}")
    lines += ["",
              "_وُلِّدت تلقائيًا بواسطة engine/drive_tree.py — لا تُعدَّل يدويًا._"]
    return "\n".join(lines)


def render(store=None):
    """كتابة التقرير + مزامنة صورة الشجرة في الحالة."""
    store = store or Store()
    S = store.rows_all()
    spec = tree_spec()
    changed = False
    existing = S.get("drive_tree", [])
    if existing and existing[0].get("digest") == spec["digest"]:
        existing[0]["last_rendered"] = dt.date.today().isoformat()
        changed = True
        S["drive_tree"] = existing
    else:
        row = dict(spec)
        row["added_at"] = dt.date.today().isoformat()
        row["last_rendered"] = dt.date.today().isoformat()
        S["drive_tree"] = [row]
        changed = True
    if changed:
        store.commit(S, "drive_tree_render")

    md = _tree_text()
    out = os.path.join(REPORTS, "master-os-drive-tree.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    log_event("drive_tree_rendered", digest=spec["digest"])
    print(f"✅ تقرير الشجرة → reports/master-os-drive-tree.md")
    return md


def checklist():
    """قائمة إنشاء قابلة للتنفيذ يدويًا (بدون كتابة حالة)."""
    print("""
قائمة إنشاء مجلدات Google Drive — Abdulrahman_Master_OS
=======================================================
أنشئ المجلدات التالية بالترتيب، ثم ضع الملفات داخل كل مجلد وفق الشجرة:
""")
    for path, purpose in folder_paths():
        print(f"  [ ] {path}\n      ↳ {purpose}")
    print("""
ملفات ورقائق العمل داخل كل مجلد (حسب الشجرة المعيارية):
""")
    for f in MASTER_TREE:
        print(f"  📂 {f['name']}/")
        for (kind, name, purpose) in f["children"]:
            print(f"      {TYPE_ICON[kind]} {name}  ({TYPE_AR[kind]} — {purpose})")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "render":
        render()
    elif cmd == "checklist":
        checklist()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

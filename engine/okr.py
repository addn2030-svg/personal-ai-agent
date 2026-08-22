# -*- coding: utf-8 -*-
"""
OKR Engine — أهداف ونتائج رئيسية قابلة للقياس (أداة يوم الأحد: اربط قرارك بـOKR مصغر).
  python3 engine/okr.py add "إطلاق المشروع التجريبي" --krs "أول 5 مستخدمين|إيراد أول 1000 ريال|قرار العقد موثق"
  python3 engine/okr.py checkin OKR-001 0.4 --kr 1 --note "تقدم الأسبوع"
  python3 engine/okr.py list
"""
import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event


def _flag(name, default=None):
    if f"--{name}" in sys.argv:
        i = sys.argv.index(f"--{name}")
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def add():
    title = sys.argv[2]
    krs = [k.strip() for k in (_flag("krs") or "").split("|") if k.strip()]
    st = Store(); S = st.rows_all()
    oid = f"OKR-{len(S['okrs']) + 1:03d}"
    S["okrs"].append({"id": oid, "objective": title,
                      "quarter": _flag("quarter") or f"{dt.date.today().year}-Q{(dt.date.today().month - 1)//3 + 1}",
                      "krs": [{"text": k, "progress": 0.0, "target": 1.0} for k in krs],
                      "status": "ACTIVE", "created_at": dt.date.today().isoformat(), "checkins": []})
    st.commit(S, "okr_added", okr=oid)
    log_event("OKR_ADDED", okr=oid, krs=len(krs))
    print(f"🎯 {oid} «{title}» — {len(krs)} نتائج رئيسية (سجل تقدمك أسبوعيًا: checkin)")


def checkin():
    oid, val = sys.argv[2], float(sys.argv[3])
    kr_i = int(_flag("kr", 0)) - 1
    st = Store(); S = st.rows_all()
    o = next((x for x in S["okrs"] if x["id"] == oid and x["status"] == "ACTIVE"), None)
    if not o:
        sys.exit("❌ لا هدف نشط بهذا المعرف")
    val = max(0.0, min(1.0, val))
    entry = {"date": dt.date.today().isoformat(), "value": val, "kr": kr_i + 1, "note": _flag("note") or ""}
    if 0 <= kr_i < len(o["krs"]):
        o["krs"][kr_i]["progress"] = val
    else:
        for k in o["krs"]:
            k["progress"] = max(k["progress"], val)
    o["checkins"].append(entry)
    avg = sum(k["progress"] for k in o["krs"]) / len(o["krs"])
    if avg >= 0.99:
        o["status"] = "DONE"
    st.commit(S, "okr_checkin", okr=oid, value=val)
    log_event("OKR_CHECKIN", okr=oid, value=val)
    bar = "█" * int(avg * 10) + "░" * (10 - int(avg * 10))
    print(f"✅ {oid} — [{bar}] {avg:.0%}")
    if avg < 0.4 and len(o["checkins"]) >= 2:
        print("   ⚠️ هدف متعثر — راجع السبب أو عدّل النتائج (بند تضخم النطاق عندك؟)")


def listing():
    S = Store().rows_all()
    if not S["okrs"]:
        print("لا أهداف OKR بعد — أنشئ أولًا بعد حسم قرار الغد.")
        return
    for o in S["okrs"]:
        avg = sum(k["progress"] for k in o["krs"]) / len(o["krs"])
        bar = "█" * int(avg * 10) + "░" * (10 - int(avg * 10))
        print(f"{o['id']} [{o['status']}] {o['objective']} — {bar} {avg:.0%} ({o['quarter']})")
        for i, k in enumerate(o["krs"], 1):
            kb = "▓" * int(k["progress"] * 8) + "·" * (8 - int(k["progress"] * 8))
            print(f"   KR{i} {kb} {k['progress']:.0%} — {k['text'][:50]}")


if __name__ == "__main__":
    {"add": add, "checkin": checkin, "list": listing}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()

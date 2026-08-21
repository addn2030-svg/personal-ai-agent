# -*- coding: utf-8 -*-
"""
يستورد بنود صندوق اليوم (data/inbox.csv — مخرجات tools/daily-inbox.html)
إلى الأقسام الصحيحة في **مخزن الحالة الموحد** (data/state.json) — لا يكتب في الشيت مباشرة.
التشغيل:  python3 engine/import_inbox.py
"""
import csv
import datetime as dt
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

INBOX = os.path.join(BASE, "data", "inbox.csv")
TODAY = dt.date.today()

if not os.path.exists(INBOX):
    print("لا يوجد data/inbox.csv — صدّر الملف من tools/daily-inbox.html أولاً.")
    raise SystemExit(0)

store = Store()
S = store.rows_all()

def next_patient_code():
    codes = []
    for r in S["followups"]:
        m = re.match(r"P-(\d+)", str(r.get("الرمز") or ""))
        if m:
            codes.append(int(m.group(1)))
    return f"P-{(max(codes) + 1) if codes else 101}"

def find_project(text):
    for p in S["projects"]:
        name = str(p.get("المشروع") or "")
        if name and len(name) > 2 and name in text:
            return name
    return None

rows = list(csv.DictReader(open(INBOX, encoding="utf-8-sig")))
added = {"مهمة": [], "فكرة": [], "سريري": [], "قرار": []}

for r in rows:
    rtype = (r.get("التصنيف") or "").strip()
    title = (r.get("العنوان") or "").strip()
    kind = (r.get("النوع") or "قسم").strip()
    prio = (r.get("الأولوية") or "متوسطة").strip()
    due = (r.get("الموعد") or "").strip()
    note = (r.get("ملاحظة") or "").strip()
    if not title:
        continue
    due_d = dt.date.fromisoformat(due) if re.match(r"^\d{4}-\d{2}-\d{2}$", due) else None

    if rtype == "مهمة":
        S["tasks"].append({"العنوان": title, "النوع": kind, "الأولوية": prio, "الموعد النهائي": due_d,
                           "الحالة": "لم تبدأ", "السياق/المشروع": "", "المصدر": "صندوق الصوت", "ملاحظات": note})
        added["مهمة"].append(title)
    elif rtype == "فكرة":
        proj = find_project(title + " " + note)
        if proj:
            for p in S["projects"]:
                if p.get("المشروع") == proj:
                    old = p.get("ملاحظات") or ""
                    p["ملاحظات"] = str(old) + (" | " if old else "") + f"💡 {TODAY}: {title}"
            added["فكرة"].append(f"{title} (أُلحقت بمشروع {proj})")
        else:
            S["projects"].append({"المشروع": title[:40], "المجال": kind if kind != "قسم" else "عام",
                                  "الحالة": "فكرة", "آخر تقدم": TODAY, "الخطوة التالية": title,
                                  "الأولوية": "منخفضة", "تكلفة شهرية (ريال)": 0, "ملاحظات": "من صندوق الصوت"})
            added["فكرة"].append(title)
    elif rtype == "سريري":
        m = re.search(r"P-\d{3}", note)
        code = m.group(0) if m else next_patient_code()
        review = "نعم" if ("مراجعة" in title or "مراجعة" in note or "نعم" in note) else "لا"
        S["followups"].append({"الرمز": code, "الحالة السريرية (مجهلة)": title, "آخر زيارة": TODAY,
                               "الموعد القادم": due_d, "يحتاج مراجعة خطة": review, "ملاحظات": note})
        added["سريري"].append(f"{code} — {title}")
    elif rtype == "قرار":
        S["decisions"].append({"التاريخ": TODAY, "القرار": title, "البدائل المدروسة": "", "الخيار": "",
                               "النتيجة المتوقعة": "", "تاريخ المراجعة": None, "النتيجة الفعلية": None,
                               "الحالة": "قيد التنفيذ", "التقييم/الدرس": "من صندوق الصوت"})
        S["waiting_for"].append({"item": f"تنفيذ قرار: {title}", "source": "قرارات",
                                 "expected_from": "داخلي", "since": TODAY, "follow_up_date": None})
        added["قرار"].append(title)

store.commit(S, "inbox_import", items={k: len(v) for k, v in added.items()})

# أرشفة الاستيراد وتفريغ الصندوق
stamp = TODAY.strftime("%Y%m%d-%H%M%S")
log = os.path.join(BASE, "data", f"inbox-imported-{stamp}.csv")
os.replace(INBOX, log)

total = sum(len(v) for v in added.values())
print(f"✅ استُورد {total} بندًا إلى مخزن الحالة الموحد (state.json v{store.data['meta']['version']}):")
for k, v in added.items():
    if v:
        print(f"   • {k}: {len(v)} — " + "؛ ".join(x[:60] for x in v))
print(f"📦 الأرشيف: {os.path.basename(log)}")
print("▶️ الآن حدّث اللوحة:  python3 engine/chief_of_staff.py")

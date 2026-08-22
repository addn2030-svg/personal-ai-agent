# -*- coding: utf-8 -*-
"""
Energy Log — سجل الطاقة والإرهاق (بروتوكول الوقاية من الإرهاق — تبويبك 2008).
  python3 engine/energy_log.py 7 3 --note "يوم جيد"     # طاقة 7، إرهاق 3
  python3 engine/energy_log.py stats
ومن تيليجرام مباشرة: أرسل «طاقة 7 إرهاق 3»
"""
import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store


def log(energy, fatigue, note=""):
    st = Store(); S = st.rows_all()
    today = dt.date.today().isoformat()
    S["energy_log"] = [e for e in S["energy_log"] if e["date"] != today]  # آخر قيد اليوم فقط
    S["energy_log"].append({"date": today, "energy": energy, "fatigue": fatigue, "note": note})
    S["energy_log"].sort(key=lambda e: e["date"])
    st.commit(S, "energy_logged", energy=energy, fatigue=fatigue)
    print(f"🔋 اليوم: طاقة {energy}/10 · إرهاق {fatigue}/10" + (f" — {note}" if note else ""))
    if fatigue >= 7:
        print("   ⚠️ إرهاق عالٍ — فعّل بروتوكول التعافي: NSDR بعد الظهر + Digital Sunset قبل النوم.")


def stats():
    S = Store().rows_all()
    last = S["energy_log"][-7:]
    if not last:
        print("لا قيود بعد — سجّل يومك: python3 engine/energy_log.py 7 3")
        return
    e = sum(x["energy"] for x in last) / len(last)
    f = sum(x["fatigue"] for x in last) / len(last)
    print(f"آخر {len(last)} أيام: طاقة {e:.1f} · إرهاق {f:.1f}")
    if f > e:
        print("🚨 نمط خطر: الإرهاق أعلى من الطاقة — راجع باب النوم/التعافي (نقطة ضعفك المسجلة)")
    for x in last:
        print(f"  {x['date']} طاقة {x['energy']} · إرهاق {x['fatigue']}" + (f" — {x['note']}" if x.get("note") else ""))


if __name__ == "__main__":
    if sys.argv[1:3] and sys.argv[1].isdigit():
        note = " ".join(sys.argv[4:]) if "--note" in sys.argv else ""
        log(int(sys.argv[1]), int(sys.argv[2]), note)
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats()
    else:
        print(__doc__)

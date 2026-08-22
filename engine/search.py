# -*- coding: utf-8 -*-
"""
Full-text Search — البحث النصي في كل أصولك (الطبقة الأولى من RAG قبل التضمينات).
يبحث في: كل ملفات md/html بالمستودع + نص عقد PDF (إن وُجد مستخرجًا) + الحالة (مهام/قرارات/انتظار/مصادر).

  python3 engine/search.py "نص البحث" [عدد النتائج]
"""
import glob
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCOPE = ["docs", "prompts", "materials", "evaluation", "reports", "tools"]


def search(q, top=12):
    qn = q.replace("أ", "ا").replace("إ", "ا")
    hits = []
    # ملفات نصية
    for scope in SCOPE:
        for f in glob.glob(os.path.join(BASE, scope, "**", "*.*"), recursive=True):
            if not f.endswith((".md", ".html", ".txt")):
                continue
            try:
                txt = open(f, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            t = txt.replace("أ", "ا").replace("إ", "ا")
            if qn in t:
                i = t.find(qn)
                snippet = txt[max(0, i-60):i+120].replace("\n", " ")
                hits.append((f.replace(BASE + "/", ""), snippet))
    # الحالة
    from store import Store
    S = Store().rows_all()
    for t in S["tasks"]:
        if qn in (t.get("العنوان") or "").replace("أ", "ا"):
            hits.append((f"حالة/مهام", f"[{t.get('الأولوية')}] {t['العنوان']} — {t.get('الحالة')}"))
    for d in S["decisions"]:
        if qn in str(d.get("القرار", "")).replace("أ", "ا"):
            hits.append(("حالة/قرارات", f"{d.get('القرار')} — {d.get('الحالة')}"))
    for w in S["waiting_for"]:
        if qn in str(w.get("task") or "").replace("أ", "ا"):
            hits.append(("حالة/انتظار", f"{w['task']} [{w.get('status')}]"))
    for k in S.get("knowledge_sources", []):
        if qn in (k["source"] + " " + k.get("key_idea", "")).replace("أ", "ا"):
            hits.append(("مكتبة", f"{k['source']} — {k.get('status')}"))
    for w in S.get("weakness_protocols", []):
        if qn in (w["weakness"] + w.get("replacement_rules", "")).replace("أ", "ا"):
            hits.append(("نقاط الضعف", f"{w['weakness']} — {w.get('week_status')}"))
    return hits[:top]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit()
    q = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    res = search(q, top)
    print(f"🔍 نتائج «{q}»: {len(res)}")
    for src, snip in res:
        print(f"  ── {src}\n     {snip[:150]}")
    if not res:
        print("لا نتائج — جرّب كلمة أقصر.")

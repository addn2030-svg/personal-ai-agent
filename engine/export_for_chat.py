# -*- coding: utf-8 -*-
"""
يصدّر «سياق عبدالرحمن» في ملف مضغوط جاهز للّصق في ChatGPT/Claude
(reports/chat-context.md) — الجسر بين محركك الحتمي وعقل LLM.

التشغيل:  python3 engine/export_for_chat.py
ثم: افتح reports/chat-context.md ← انسخه ← الصقه في ChatGPT مع حزمة prompts/chief-of-staff.md
"""
import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store

TODAY = dt.date.today()
OUT = os.path.join(BASE, "reports", "chat-context.md")

S = Store().rows_all()
tasks = [t for t in S["tasks"] if t.get("الحالة") != "منجزة"]
prio = {"عالية": 0, "متوسطة": 1, "منخفضة": 2}
tasks.sort(key=lambda t: (prio.get(t.get("الأولوية"), 3),
                          (TODAY - t["الموعد النهائي"]).days if isinstance(t.get("الموعد النهائي"), dt.date) and t["الموعد النهائي"] < TODAY else 0))
drs = [d for d in S.get("decision_requests", []) if d.get("status") == "PENDING"]
dec_due = [d for d in S["decisions"] if isinstance(d.get("تاريخ المراجعة"), dt.date)
           and d["تاريخ المراجعة"] <= TODAY + dt.timedelta(days=7) and d.get("الحالة") != "منفذ"]
waiting = sorted([w for w in S["waiting_for"] if w.get("status") != "CLOSED"],
                 key=lambda w: (TODAY - w["expected_by"]).days if isinstance(w.get("expected_by"), dt.date) else 0, reverse=True)
projects = S["projects"]
stalled = [p for p in projects if p.get("الحالة") == "نشط" and isinstance(p.get("آخر تقدم"), dt.date)
           and (TODAY - p["آخر تقدم"]).days > 30]
reviews = [r for r in S.get("learning_reviews", []) if r.get("status") in ("DUE", "PRESENTED")][:2]
pending_actions = [a for a in S["action_queue"] if a["status"] == "PENDING_APPROVAL"]
leads_active = [l for l in S["leads"] if l.get("الحالة") in ("جديد", "تم التواصل", "انتظار رد", "عرض")]


def d(x):
    return str(x)[:10] if isinstance(x, (dt.date, dt.datetime)) else (str(x) if x else "—")


L = []
L.append(f"# 📋 سياق عبدالرحمن — {TODAY.isoformat()} (مصدَّر آليًا من نظامك المحلي)")
L.append("> الصق هذا في بداية محادثة ChatGPT مع حزمة «Chief of Staff» (prompts/chief-of-staff.md).")
L.append("> بعد الحوار: أعد ما ينتج من مهام/قرارات إلى النظام عبر صندوق اليوم (tools/daily-inbox.html) أو مباشرة.")
L.append("")
L.append("## 🎯 أهم المهام المفتوحة (6)")
for t in tasks[:6]:
    late = f" ⚠️متأخرة{(TODAY - t['الموعد النهائي']).days}ي" if isinstance(t.get("الموعد النهائي"), dt.date) and t["الموعد النهائي"] < TODAY else ""
    L.append(f"- [{t.get('الأولوية')}] {t['العنوان']} (موعد {d(t.get('الموعد النهائي'))}){late}")
L.append("")
if drs:
    L.append("## 🧭 طلبات قرار مفتوحة")
    for r in drs:
        L.append(f"- {r['id']}: {r['title']} — خيارات: {' / '.join(r['options'])} (المهلة {d(r.get('deadline'))})")
if dec_due:
    L.append("## 📊 قرارات مستحقة المراجعة (متوقع مقابل فعلي)")
    for x in dec_due:
        L.append(f"- «{x['القرار']}» (الخيار: {x.get('الخيار')}) — متوقع: {x.get('النتيجة المتوقعة')} | فعلي: {x.get('النتيجة الفعلية') or 'لم يُسجل'}")
if waiting:
    L.append("## ⏸️ ننتظر")
    for w in waiting[:6]:
        days = max(0, (TODAY - w["expected_by"]).days) if isinstance(w.get("expected_by"), dt.date) else 0
        tag = " ⚠️ متأخر" if w.get("status") == "OVERDUE" else (" (متوقع قريبًا)" if days == 0 else "")
        L.append(f"- {w['task']} — من {w.get('expected_from') or '—'} (منذ {days} يوم{tag})")
L.append("## 🤖 المشاريع")
counts = {}
for p in projects:
    counts[p["الحالة"]] = counts.get(p["الحالة"], 0) + 1
L.append("- " + " | ".join(f"{k} {v}" for k, v in counts.items()))
if stalled:
    L.append("- ⚠️ نشطة لكنها متوقفة: " + "، ".join(f"{p['المشروع']} ({(TODAY - p['آخر تقدم']).days} يومًا)" for p in stalled))
L.append("- النشطة: " + "، ".join(p["المشروع"] for p in projects if p["الحالة"] == "نشط"))
L.append("")
L.append("## 💼 فرص نشطة (مع خط الأنابيب)")
for l in leads_active[:6]:
    L.append(f"- {l['الجهة']} — {l['الخدمة']} [{l['الحالة']}] آخر تواصل {d(l.get('آخر تواصل'))}")
L.append("")
if pending_actions:
    L.append(f"## 🛂 {len(pending_actions)} إجراء في طابور الاعتماد (مسودات جاهزة)")
    for a in pending_actions[:3]:
        L.append(f"- {a['action_id']}: {a['content'][:80]}...")
if reviews:
    L.append("## 📚 مراجعات تعلم مستحقة")
    for r in reviews:
        L.append(f"- {r['concept_title']} ({r['est_minutes']} دقائق)")
L.append("")
L.append("---")
L.append("**تعليمات للوكيل:** تصرف كرئيس مكتب رقمي (Chief of Staff) لعبدالرحمن وفق حزمة الأوامر المرفقة في الـProject. "
         "ابدأ بالبريف: أهم 3 أولويات، ما يحتاج قراره، خطر واحد، فرصة واحدة — ثم أجب على أسئلته مستندًا **فقط** لهذا السياق، "
         "وما لا تجده هنا قل عنه «غير متوفر في السياق». افصل: حقيقة من السياق / استنتاج / توصية.")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print(f"✅ صُدّر السياق → reports/chat-context.md ({len(''.join(L))} حرفًا — مضغوط للّصق المباشر)")
print("   الخطوة التالية: انسخه + حزمة prompts/chief-of-staff.md إلى ChatGPT (Project واحد ثابت)")

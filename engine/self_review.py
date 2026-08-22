# -*- coding: utf-8 -*-
"""Weekly self-review: what was learned, proposed, tested and needs human judgment."""
import datetime as dt, json, os
from reflection_engine import experiences, reflect
from skill_registry import list_skills
from behavior_model import active

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS=os.path.join(BASE,"reports")

def build():
    os.makedirs(REPORTS,exist_ok=True)
    new_lessons=reflect()
    skills=list_skills(); exp=experiences(200)
    pending=[s for s in skills if s["status"] in {"CANDIDATE","TESTING","APPROVED"}]
    act=[s for s in skills if s["status"]=="ACTIVE"]
    inferred=[x for x in active(0) if x["status"]=="INFERRED"]
    lines=[f"# 🧠 مراجعة التعلم الذاتي — {dt.date.today().isoformat()}","",
           f"- الخبرات المرصودة: **{len(exp)}**",f"- دروس جديدة هذا التشغيل: **{len(new_lessons)}**",
           f"- مهارات نشطة: **{len(act)}**",f"- مهارات تحتاج مراجعة/ترقية: **{len(pending)}**","",
           "## مهارات تحتاج حكمك"]
    if not pending: lines.append("- لا شيء ✅")
    for s in pending:
        m=s["metrics"]; rate=(m["passed"]/m["tests"]*100) if m["tests"] else 0
        lines.append(f"- **{s['id']} v{s['version']} — {s['name']}** | {s['risk_tier']} | {s['status']} | اختبارات {m['passed']}/{m['tests']} ({rate:.0f}%) | أدلة {len(s['evidence_ids'])}")
    lines += ["","## استنتاجات سلوكية غير مؤكدة"]
    if not inferred: lines.append("- لا شيء")
    for x in inferred[:12]: lines.append(f"- {x['id']} ({x['confidence']:.0%}): {x['statement']} — المصدر: {x['source']}")
    lines += ["","## قواعد الحوكمة","- LOW يمكن أن يُعتمد تلقائيًا بعد نجاح الاختبارات، لكنه لا ينفذ أثرًا خارجيًا.",
              "- REVIEW يحتاج موافقة بشرية قبل التفعيل.","- LOCKED لا يُفعّل تلقائيًا مهما كانت نتيجة الاختبار.",
              "- لا تُحوّل بيانات المرضى المعرِّفة إلى procedural memory أو GitHub."]
    out=os.path.join(REPORTS,"self-improvement-latest.md")
    open(out,"w",encoding="utf-8").write("\n".join(lines)+"\n")
    return out

if __name__=="__main__": print(build())

# -*- coding: utf-8 -*-
"""Deterministic router before any LLM call.
Routes intent to one primary agent and records why. Ambiguous inputs stay with chief_of_staff.
"""
import json, re, sys
from permissions import authorize

ROUTES = [
    ("clinical", [r"مريض|سريري|علاج طبيعي|ألم|تشخيص|تمرين علاجي|shoulder|lumbar|patient"]),
    ("health", [r"طاقة|إرهاق|نوم|تعافي|صحة|وزن|رياضة"]),
    ("finance", [r"مال|راتب|قرض|اشتراك|فاتورة|ميزانية|تكلفة|إيراد|finance|subscription"]),
    ("learning", [r"تعلم|دورة|كتاب|مراجعة|إتقان|lean six sigma|study"]),
    ("projects", [r"مشروع|مهمة|okr|موعد نهائي|خطة تنفيذ|project|task"]),
    ("research", [r"بحث|مصدر|دراسة|مرجع|evidence|research"]),
    ("social", [r"سوشال|تواصل اجتماعي|انستغرام|linkedin|x |تويتر|تعليق|منشور"]),
    ("communications", [r"رسالة|ايميل|واتساب|تلغرام|telegram|email|reply"]),
]

def route(text: str):
    t = text.lower().strip()
    scored = []
    for agent, pats in ROUTES:
        score = sum(1 for p in pats if re.search(p, t, re.I))
        if score:
            scored.append((score, agent))
    scored.sort(reverse=True)
    if not scored:
        return {"agent":"chief_of_staff","confidence":0.55,"reason":"no specific domain matched"}
    top_score, top_agent = scored[0]
    tied = [a for s,a in scored if s == top_score]
    if len(tied) > 1:
        return {"agent":"chief_of_staff","confidence":0.60,"reason":"cross-domain ambiguity", "candidates":tied}
    return {"agent":top_agent,"confidence":min(.95,.65+.1*top_score),"reason":f"matched {top_score} domain signal(s)"}

def plan(text: str):
    r = route(text)
    read = authorize(r["agent"], "read_state")
    draft = authorize(r["agent"], "draft")
    r["capabilities"] = {"read_state":read.allowed,"draft":draft.allowed}
    return r

if __name__ == "__main__":
    print(json.dumps(plan(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))

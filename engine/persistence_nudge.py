# -*- coding: utf-8 -*-
"""Suggests what should persist after a session without blindly memorizing everything."""
from __future__ import annotations
import json, re

DURABLE_PATTERNS = [
    ("preference", r"أفضل|أفضّل|لا أريد|دائمًا|عادة|prefer|always|usually|do not"),
    ("decision", r"قررت|اعتمد|قرار|قررنا|decision|approved"),
    ("role", r"رئيس قسم|مدير|أعمل في|مسؤوليتي|role|responsib"),
    ("workflow", r"كل صباح|كل أسبوع|متابعة|إجراء|workflow|every morning|weekly"),
    ("source", r"المصدر|وثيقة|ملف|مرجع|source|document|reference"),
]
SENSITIVE = re.compile(r"token|password|secret|api[_ -]?key|رقم هوية|سجل طبي|اسم المريض", re.I)

def classify(text):
    if not text or SENSITIVE.search(text): return {"persist":False,"reason":"sensitive/empty","types":[]}
    types=[name for name,pat in DURABLE_PATTERNS if re.search(pat,text,re.I)]
    return {"persist":bool(types),"reason":"durable signal" if types else "likely transient","types":types}

def nudge(text):
    c=classify(text)
    if not c["persist"]: return c
    c["question"]="هذه المعلومة تبدو قابلة للاستمرار. هل تُحفظ كحقيقة/تفضيل/قرار مع المصدر والتاريخ؟"
    return c

if __name__=="__main__":
    import sys
    print(json.dumps(nudge(" ".join(sys.argv[1:])),ensure_ascii=False,indent=2))

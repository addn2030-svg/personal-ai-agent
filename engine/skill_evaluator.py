# -*- coding: utf-8 -*-
"""Regression evaluator and promotion gate for generated skills."""
from __future__ import annotations
import json, os, sys
from skill_registry import list_skills, record_test, set_status

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES=os.path.join(BASE,"evaluation","self_improvement_cases.json")


def load_cases():
    if not os.path.exists(CASES): return []
    return json.load(open(CASES,encoding="utf-8"))

def evaluate(skill_id):
    skill=next(x for x in list_skills() if x["id"]==skill_id)
    body=open(os.path.join(BASE,skill["file"]),encoding="utf-8").read()
    cases=[c for c in load_cases() if c.get("domain") in {skill["domain"],"any"}]
    results=[]
    for c in cases:
        ok=True
        for must in c.get("must_contain",[]): ok=ok and must.lower() in body.lower()
        for ban in c.get("must_not_contain",[]): ok=ok and ban.lower() not in body.lower()
        results.append({"case":c["id"],"passed":bool(ok)})
        record_test(skill_id,ok)
    passed=sum(r["passed"] for r in results); total=len(results)
    rate=passed/total if total else 0.0
    return {"skill_id":skill_id,"passed":passed,"total":total,"rate":rate,"results":results}

def promotion_decision(skill_id):
    skill=next(x for x in list_skills() if x["id"]==skill_id); r=evaluate(skill_id)
    if r["total"]==0: return {**r,"decision":"HOLD","reason":"no regression cases"}
    if r["rate"]<0.9: return {**r,"decision":"REJECT_OR_REVISE","reason":"pass rate below 90%"}
    if skill["risk_tier"]=="low":
        set_status(skill_id,"APPROVED","auto-approved after regression pass")
        return {**r,"decision":"AUTO_APPROVED","reason":"low-risk + >=90% tests"}
    return {**r,"decision":"HUMAN_REVIEW","reason":"review/locked skills need explicit approval"}

if __name__=="__main__":
    if len(sys.argv)<2: raise SystemExit("usage: skill_evaluator.py SK-...")
    print(json.dumps(promotion_decision(sys.argv[1]),ensure_ascii=False,indent=2))

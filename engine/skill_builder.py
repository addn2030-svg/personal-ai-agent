# -*- coding: utf-8 -*-
"""Builds a conservative procedural candidate from a reflected lesson.
An LLM may later rewrite the wording, but evidence and safety gates stay deterministic.
"""
import json, os, sys
from reflection_engine import _load_lessons, experiences, propose_skill


def build(lesson_id):
    lessons=_load_lessons(); l=next(x for x in lessons["lessons"] if x["id"]==lesson_id)
    ev={e["id"]:e for e in experiences(1000)}
    rows=[ev[eid] for eid in l["evidence_ids"] if eid in ev]
    successes=[r for r in rows if str(r.get("outcome")).lower() in {"success","successful","true","done"}]
    corrections=[r.get("correction") for r in rows if r.get("correction")]
    name=(" / ".join(l.get("tags") or []) or l["kind"]).title()+" workflow"
    purpose=f"Reusable {l['domain']} procedure learned from {len(rows)} recorded experiences."
    steps=["1. Reconfirm the current context, owner, deadline and source before acting."]
    if successes:
        for i,r in enumerate(successes[-3:],start=2): steps.append(f"{i}. Preserve successful pattern: {r['summary'][:220]}")
    else:
        steps.append("2. Use the simplest reversible next action and capture the outcome.")
    n=len(steps)+1
    for c in corrections[-3:]:
        steps.append(f"{n}. Avoid/correct: {c[:220]}"); n+=1
    steps.append(f"{n}. Before any external effect, use the existing approval/executor gate.")
    steps.append(f"{n+1}. Record outcome; if corrected again, feed it back as a new experience.")
    confidence=min(.9,.55+.05*len(rows)+.05*len(successes))
    return propose_skill(lesson_id,name,purpose,"\n".join(steps),confidence)

if __name__=="__main__":
    if len(sys.argv)<2: raise SystemExit("usage: skill_builder.py LS-...")
    print(json.dumps(build(sys.argv[1]),ensure_ascii=False,indent=2))

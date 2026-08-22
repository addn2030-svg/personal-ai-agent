# -*- coding: utf-8 -*-
"""Loads only the active skills relevant to the routed domain."""
import os
from skill_registry import list_skills, record_use

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def active_for(domain):
    return [s for s in list_skills("ACTIVE") if s["domain"] in {domain,"general"}]

def context_for(domain, max_chars=6000):
    chunks=[]; used=[]; total=0
    for s in active_for(domain):
        txt=open(os.path.join(BASE,s["file"]),encoding="utf-8").read()
        if total+len(txt)>max_chars: continue
        chunks.append(f"\n--- SKILL {s['id']} v{s['version']} ---\n{txt}"); used.append(s["id"]); total+=len(txt)
        record_use(s["id"])
    return {"domain":domain,"skill_ids":used,"context":"".join(chunks)}

if __name__=="__main__":
    import sys,json
    print(json.dumps(context_for(sys.argv[1] if len(sys.argv)>1 else "general"),ensure_ascii=False,indent=2))

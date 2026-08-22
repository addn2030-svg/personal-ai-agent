# -*- coding: utf-8 -*-
"""Experience -> reflection -> lesson -> skill candidate pipeline.
No LLM dependency is required for the deterministic trigger layer.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os
from skill_registry import create_candidate
try:
    from store import log_event
except Exception:
    def log_event(*a, **k): pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, "data", "self_improvement")
EXP = os.path.join(DIR, "experiences.jsonl")
LESSONS = os.path.join(DIR, "lessons.json")


def _ensure(): os.makedirs(DIR, exist_ok=True)

def capture(kind, domain, summary, outcome=None, correction=None, source="runtime", tags=None):
    _ensure(); ts=dt.datetime.now().isoformat(timespec="seconds")
    raw=f"{ts}|{kind}|{domain}|{summary}|{correction or ''}"
    eid="EX-"+hashlib.sha256(raw.encode()).hexdigest()[:10].upper()
    rec={"id":eid,"ts":ts,"kind":kind,"domain":domain,"summary":summary[:1200],
         "outcome":outcome,"correction":correction,"source":source,"tags":tags or []}
    with open(EXP,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    log_event("experience_captured", experience=eid, domain=domain, kind=kind)
    return rec

def experiences(limit=500):
    _ensure()
    if not os.path.exists(EXP): return []
    rows=[]
    with open(EXP,encoding="utf-8") as f:
        for line in f:
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows[-limit:]

def _load_lessons():
    _ensure()
    if not os.path.exists(LESSONS): return {"schema":"lessons/1","lessons":[]}
    return json.load(open(LESSONS,encoding="utf-8"))

def _save_lessons(x):
    tmp=LESSONS+".tmp"; json.dump(x,open(tmp,"w",encoding="utf-8"),ensure_ascii=False,indent=2); os.replace(tmp,LESSONS)

def reflect(min_repeats=3):
    rows=experiences(); groups={}
    for e in rows:
        key=(e["domain"], tuple(sorted(e.get("tags") or [])), e["kind"])
        groups.setdefault(key,[]).append(e)
    out=[]; data=_load_lessons(); existing={l["fingerprint"] for l in data["lessons"]}
    for (domain,tags,kind), items in groups.items():
        corrections=[i for i in items if i.get("correction")]
        failures=[i for i in items if str(i.get("outcome")).lower() in {"fail","failed","failure","false"}]
        trigger=len(items)>=min_repeats or len(corrections)>=2 or len(failures)>=2
        if not trigger: continue
        fp=hashlib.sha256((domain+"|"+kind+"|"+"|".join(tags)).encode()).hexdigest()[:16]
        if fp in existing: continue
        lid="LS-"+fp.upper()
        lesson={"id":lid,"fingerprint":fp,"domain":domain,"kind":kind,"tags":list(tags),
                "evidence_ids":[x["id"] for x in items[-8:]],"repeats":len(items),
                "corrections":len(corrections),"failures":len(failures),
                "lesson":f"Repeated {kind} pattern in {domain}; preserve successful structure and explicitly avoid observed corrections/failures.",
                "status":"OPEN","created_at":dt.datetime.now().isoformat(timespec="seconds")}
        data["lessons"].append(lesson); existing.add(fp); out.append(lesson)
        log_event("lesson_created", lesson=lid, domain=domain)
    if out: _save_lessons(data)
    return out

def propose_skill(lesson_id, name, purpose, procedure, confidence=.65):
    data=_load_lessons(); l=next(x for x in data["lessons"] if x["id"]==lesson_id)
    rec=create_candidate(name,l["domain"],purpose,procedure,l["evidence_ids"],confidence)
    l["status"]="SKILL_PROPOSED"; l["skill_id"]=rec["id"]; _save_lessons(data)
    log_event("skill_candidate_created", skill=rec["id"], lesson=lesson_id)
    return rec

if __name__=="__main__":
    import sys
    cmd=sys.argv[1] if len(sys.argv)>1 else "reflect"
    if cmd=="reflect":
        for x in reflect(): print(x["id"],x["domain"],x["repeats"],x["lesson"])
    elif cmd=="capture":
        print(capture(sys.argv[2],sys.argv[3]," ".join(sys.argv[4:])))

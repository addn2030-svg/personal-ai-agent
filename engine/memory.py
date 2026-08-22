# -*- coding: utf-8 -*-
"""Layered memory: working, episodic and durable semantic memory.
The authoritative mutable business state remains data/state.json; this module adds memory views without replacing Store.
"""
import datetime as dt, json, os, hashlib
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM_DIR = os.path.join(BASE, "data", "memory")
WORKING = os.path.join(MEM_DIR, "working.json")
EPISODIC = os.path.join(MEM_DIR, "episodic.jsonl")
SEMANTIC = os.path.join(MEM_DIR, "semantic.jsonl")


def _ensure(): os.makedirs(MEM_DIR, exist_ok=True)
def _write_atomic(path, obj):
    _ensure(); tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)
    os.replace(tmp,path)

def set_working(items, ttl_hours=24):
    now = dt.datetime.now()
    _write_atomic(WORKING,{"updated_at":now.isoformat(timespec="seconds"),"expires_at":(now+dt.timedelta(hours=ttl_hours)).isoformat(timespec="seconds"),"items":items})
def get_working():
    try:
        d=json.load(open(WORKING,encoding="utf-8")); exp=dt.datetime.fromisoformat(d["expires_at"])
        return d["items"] if exp >= dt.datetime.now() else []
    except Exception: return []
def append_episode(kind, summary, refs=None, sensitivity="normal"):
    _ensure(); rec={"id":"EP-"+hashlib.sha256((kind+summary+str(dt.datetime.now())).encode()).hexdigest()[:10],"ts":dt.datetime.now().isoformat(timespec="seconds"),"kind":kind,"summary":summary,"refs":refs or [],"sensitivity":sensitivity}
    with open(EPISODIC,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    return rec
def remember_fact(subject, predicate, value, source_ref, confidence=0.8):
    _ensure(); rec={"id":"SM-"+hashlib.sha256((subject+predicate+str(value)).encode()).hexdigest()[:10],"ts":dt.datetime.now().isoformat(timespec="seconds"),"subject":subject,"predicate":predicate,"value":value,"source_ref":source_ref,"confidence":confidence}
    with open(SEMANTIC,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    return rec

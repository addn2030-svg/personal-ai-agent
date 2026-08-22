# -*- coding: utf-8 -*-
"""Behavioral model: confirmed preferences are separated from AI inferences."""
from __future__ import annotations
import datetime as dt, json, os

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR=os.path.join(BASE,"data","self_improvement")
PATH=os.path.join(DIR,"behavior_model.json")

def _load():
    os.makedirs(DIR,exist_ok=True)
    if not os.path.exists(PATH): return {"schema":"behavior/1","items":[]}
    return json.load(open(PATH,encoding="utf-8"))

def _save(x):
    tmp=PATH+".tmp"; json.dump(x,open(tmp,"w",encoding="utf-8"),ensure_ascii=False,indent=2); os.replace(tmp,PATH)

def add(statement, source, confidence=.6, confirmed=False, scope="general"):
    data=_load(); now=dt.datetime.now().isoformat(timespec="seconds")
    rec={"id":f"BM-{len(data['items'])+1:04d}","statement":statement,"scope":scope,
         "source":source,"confidence":1.0 if confirmed else float(confidence),
         "status":"CONFIRMED" if confirmed else "INFERRED","created_at":now,"updated_at":now}
    data["items"].append(rec); _save(data); return rec

def confirm(item_id):
    data=_load(); rec=next(x for x in data["items"] if x["id"]==item_id)
    rec["status"]="CONFIRMED"; rec["confidence"]=1.0; rec["updated_at"]=dt.datetime.now().isoformat(timespec="seconds"); _save(data); return rec

def contradict(item_id, evidence):
    data=_load(); rec=next(x for x in data["items"] if x["id"]==item_id)
    rec["status"]="REVIEW_REQUIRED"; rec["contradiction"]=evidence; rec["updated_at"]=dt.datetime.now().isoformat(timespec="seconds"); _save(data); return rec

def active(min_conf=.7): return [x for x in _load()["items"] if x["status"] in {"CONFIRMED","INFERRED"} and x["confidence"]>=min_conf]

if __name__=="__main__":
    for x in active(0): print(x["id"],x["status"],x["confidence"],x["statement"])

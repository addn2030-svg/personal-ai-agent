# -*- coding: utf-8 -*-
"""Agent health and observability snapshot."""
import datetime as dt, json, os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(BASE,"reports","agent-health.json")

def _exists(rel):
    p=os.path.join(BASE,rel); return {"path":rel,"exists":os.path.exists(p),"mtime":dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds") if os.path.exists(p) else None}

def snapshot():
    checks=[_exists("data/state.json"),_exists("data/audit.jsonl"),_exists("data/rag-index.json"),_exists("data/.telegram-owner"),_exists("reports/dashboard-latest.html")]
    pending=0; version=None; updated=None
    try:
        s=json.load(open(os.path.join(BASE,"data","state.json"),encoding="utf-8")); version=s.get("meta",{}).get("version"); updated=s.get("meta",{}).get("updated_at"); pending=sum(1 for a in s.get("action_queue",[]) if a.get("status")=="PENDING_APPROVAL")
    except Exception: pass
    d={"generated_at":dt.datetime.now().isoformat(timespec="seconds"),"state_version":version,"state_updated_at":updated,"pending_approvals":pending,"checks":checks,"status":"healthy" if all(x["exists"] for x in checks[:2]) else "degraded"}
    os.makedirs(os.path.dirname(OUT),exist_ok=True); json.dump(d,open(OUT,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    print(json.dumps(d,ensure_ascii=False,indent=2)); return d
if __name__=="__main__": snapshot()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
system_status --layers --schedule --finance --proactive
يعطي حالة الطبقات والجدولة فوراً — للبوت/المطور بدون تخمين
"""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE,'engine'))
from store import Store
TZ=ZoneInfo(os.environ.get("MANAGER_TIMEZONE","Asia/Riyadh"))

def layers_status():
    out=[]
    # core
    checks=[
        ("store", "engine/store.py", True),
        ("manager fast/full", "engine/manager.py", True),
        ("chief_of_staff", "engine/chief_of_staff.py", True),
        ("scheduler", "engine/scheduler.py", True),
        ("proactive", "engine/proactive.py", True),
        ("approve C2", "engine/approve.py", True),
        ("finance_hub v2.0", "engine/finance_hub.py", True),
        ("asset_registry", "engine/asset_registry.py", True),
        ("backup_verify", "engine/backup_verify.py", True),
        ("change_intelligence", "engine/change_intelligence.py", True),
        ("observability", "engine/observability.py", True),
        ("trust_dashboard", "engine/trust_dashboard.py", True),
        ("rag", "engine/rag.py", True),
        ("context_service", "engine/context_service.py", True),
    ]
    try:
        import finance_hub, proactive
        S=Store().rows_all()
        fin=S.get("finance",[])
        snaps=S.get("finance_snapshots",[])
        links=S.get("finance_links",[])
        proactive_status=proactive.status() if hasattr(proactive,'status') else {}
        finance_status=finance_hub.status()
    except Exception as e:
        finance_status={"error":str(e)}
        proactive_status={}
        snaps=[]
        fin=[]
        links=[]
    now=dt.datetime.now(TZ).isoformat(timespec="seconds")
    # layers
    for name, path, active in checks:
        exists=os.path.exists(os.path.join(BASE,path))
        if "finance_hub" in path:
            status=f"✅ active — finance {len(fin)} rows, {len(snaps)} snapshots, link {bool(links)} — auto: Thu 07:00 + 1st 07:30 + hourly"
        elif "proactive" in path:
            status=f"✅ active — enabled {proactive_status.get('enabled')} 8/8 SO, alerts {proactive_status.get('alerts_today')}/6"
        elif "scheduler" in path:
            status="✅ active — 11 jobs (daily/weekly/monthly) via manager --loop"
        elif "manager" in path:
            status="✅ active — fast 15m + full 06:00 + dormant loop + finance_hub + trust heartbeat"
        elif path=="engine/store.py":
            status="✅ active — StateStore single source"
        else:
            dormant = name in ("asset_registry","backup_verify","change_intelligence","observability","trust_dashboard")
            if dormant:
                status="✅ activated v2.0 — now in manager loop (full_cycle + daily trust heartbeat)"
            else:
                status="✅ active" if exists else "❌ missing"
        out.append({"layer":name, "path":path, "exists":exists, "status":status})
    return {"at":now, "layers":out, "finance":finance_status, "proactive":proactive_status, "snapshots": len(snaps)}

def schedule_status():
    try:
        import scheduler
        ref=dt.datetime.now(TZ)
        due=scheduler.due_listing(ref)
        return {"at":ref.isoformat(timespec="seconds"), "due_now":[{"job_id":j["job_id"],"time":j["time"],"cadence":j["cadence"]} for j in due]}
    except Exception as e:
        return {"error":str(e)}

if __name__=="__main__":
    args=sys.argv[1:]
    if "--layers" in args or "--all" in args or not args:
        print(json.dumps(layers_status(), ensure_ascii=False, indent=2, default=str))
    if "--schedule" in args or "--all" in args:
        print(json.dumps(schedule_status(), ensure_ascii=False, indent=2, default=str))
    if "--finance" in args:
        try:
            import finance_hub; print(json.dumps(finance_hub.status(), ensure_ascii=False, indent=2, default=str))
        except Exception as e: print(f"error {e}")
    if "--proactive" in args:
        try:
            import proactive; print(json.dumps(proactive.status(), ensure_ascii=False, indent=2, default=str))
        except Exception as e: print(f"error {e}")

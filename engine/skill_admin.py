# -*- coding: utf-8 -*-
"""Human control surface for learned skills.
Usage:
  python3 engine/skill_admin.py pending
  python3 engine/skill_admin.py approve SK-XXXX
  python3 engine/skill_admin.py activate SK-XXXX
  python3 engine/skill_admin.py reject SK-XXXX "reason"
  python3 engine/skill_admin.py rollback skill-slug
"""
import sys
from skill_registry import list_skills, set_status
try:
    from store import log_event
except Exception:
    def log_event(*a,**k): pass


def pending():
    rows=[x for x in list_skills() if x["status"] in {"CANDIDATE","TESTING","APPROVED"}]
    for x in rows: print(x["id"],x["status"],x["risk_tier"],f"v{x['version']}",x["name"])
    return rows

def approve(sid):
    r=set_status(sid,"APPROVED","approved by owner"); log_event("skill_approved",skill=sid); print("✅ approved",sid); return r

def activate(sid):
    r=set_status(sid,"ACTIVE","activated by owner"); log_event("skill_activated",skill=sid); print("✅ active",sid); return r

def reject(sid,note):
    r=set_status(sid,"REJECTED",note or "rejected by owner"); log_event("skill_rejected",skill=sid); print("🚫 rejected",sid); return r

def rollback(slug):
    versions=sorted([x for x in list_skills() if x["slug"]==slug],key=lambda x:x["version"],reverse=True)
    active=next((x for x in versions if x["status"]=="ACTIVE"),None)
    previous=next((x for x in versions if (not active or x["version"]<active["version"]) and x["status"] in {"RETIRED","APPROVED"}),None)
    if not previous: raise SystemExit("No previous approved/retired version available")
    if active: set_status(active["id"],"RETIRED","rolled back")
    if previous["status"]!="APPROVED": set_status(previous["id"],"APPROVED","rollback candidate")
    set_status(previous["id"],"ACTIVE","rollback activated")
    log_event("skill_rollback",slug=slug,to=previous["id"]); print("↩️ rollback",slug,"→",previous["id"]); return previous

if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else "pending"
    if cmd=="pending": pending()
    elif cmd=="approve": approve(sys.argv[2])
    elif cmd=="activate": activate(sys.argv[2])
    elif cmd=="reject": reject(sys.argv[2]," ".join(sys.argv[3:]))
    elif cmd=="rollback": rollback(sys.argv[2])
    else: raise SystemExit(__doc__)

# -*- coding: utf-8 -*-
"""Versioned procedural-memory registry for AI OS v0.6.
Skills are stored locally as metadata + Markdown bodies. Sensitive domains never auto-promote.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data", "self_improvement")
SKILLS_DIR = os.path.join(BASE, "skills", "generated")
REGISTRY = os.path.join(DATA_DIR, "skills.json")

RISK = {
    "low": {"formatting", "summarization", "personal_organization", "report_layout"},
    "review": {"administrative", "staff", "communications", "projects", "finance"},
    "locked": {"clinical", "health_safety", "permissions", "external_execution", "security"},
}


def _load():
    os.makedirs(DATA_DIR, exist_ok=True); os.makedirs(SKILLS_DIR, exist_ok=True)
    if not os.path.exists(REGISTRY):
        return {"schema":"skills/1", "skills":[]}
    with open(REGISTRY, encoding="utf-8") as f: return json.load(f)


def _save(data):
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY)


def risk_tier(domain):
    for tier, domains in RISK.items():
        if domain in domains: return tier
    return "review"


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9\u0600-\u06ff]+", "-", name.strip().lower()).strip("-")
    return s[:70] or "skill"


def create_candidate(name, domain, purpose, procedure, evidence_ids, confidence=0.6):
    data = _load(); slug = slugify(name)
    versions = [x for x in data["skills"] if x["slug"] == slug]
    v = 1 + max([x["version"] for x in versions] or [0])
    sid = f"SK-{hashlib.sha256((slug+str(v)).encode()).hexdigest()[:8].upper()}"
    tier = risk_tier(domain)
    status = "CANDIDATE"
    now = dt.datetime.now().isoformat(timespec="seconds")
    body = f"# {name}\n\n## Purpose\n{purpose}\n\n## Procedure\n{procedure.strip()}\n\n## Safety\nRisk tier: {tier}. External effects remain approval-gated.\n"
    path = os.path.join(SKILLS_DIR, f"{slug}-v{v}.md")
    with open(path, "w", encoding="utf-8") as f: f.write(body)
    rec = {"id":sid,"slug":slug,"name":name,"domain":domain,"version":v,"status":status,
           "risk_tier":tier,"confidence":float(confidence),"evidence_ids":list(evidence_ids),
           "created_at":now,"updated_at":now,"file":os.path.relpath(path, BASE).replace("\\","/"),
           "metrics":{"tests":0,"passed":0,"uses":0,"successes":0},"supersedes":versions[-1]["id"] if versions else None}
    data["skills"].append(rec); _save(data); return rec


def set_status(skill_id, status, note=""):
    allowed = {"CANDIDATE","TESTING","APPROVED","ACTIVE","RETIRED","REJECTED"}
    if status not in allowed: raise ValueError(status)
    data = _load(); rec = next(x for x in data["skills"] if x["id"] == skill_id)
    if status == "ACTIVE" and rec["risk_tier"] in {"review","locked"} and rec.get("status") != "APPROVED":
        raise PermissionError("review/locked skills require APPROVED before ACTIVE")
    if status == "ACTIVE":
        for x in data["skills"]:
            if x["slug"] == rec["slug"] and x["id"] != rec["id"] and x["status"] == "ACTIVE": x["status"] = "RETIRED"
    rec["status"] = status; rec["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    if note: rec["note"] = note
    _save(data); return rec


def record_test(skill_id, passed):
    data = _load(); rec = next(x for x in data["skills"] if x["id"] == skill_id)
    rec["metrics"]["tests"] += 1; rec["metrics"]["passed"] += int(bool(passed)); _save(data); return rec


def record_use(skill_id, success=None):
    data = _load(); rec = next(x for x in data["skills"] if x["id"] == skill_id)
    rec["metrics"]["uses"] += 1
    if success is not None: rec["metrics"]["successes"] += int(bool(success))
    _save(data); return rec


def list_skills(status=None):
    rows = _load()["skills"]
    return [x for x in rows if status is None or x["status"] == status]

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv)>1 else "list"
    if cmd == "list":
        for x in list_skills(): print(x["id"], x["status"], x["risk_tier"], f"v{x['version']}", x["name"])

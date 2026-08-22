# -*- coding: utf-8 -*-
"""Generate the Trust Dashboard: only conditions that undermine confidence or require judgment."""
import datetime as dt, json, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store
OUT=os.path.join(BASE,'reports','trust-dashboard-latest.md')

def build():
    S=Store().rows_all()
    open_dec=sum(d.get('status')=='PENDING' for d in S.get('decision_requests',[]))
    overdue=sum(w.get('status')=='OVERDUE' for w in S.get('waiting_for',[]))
    stale=sum(f.get('freshness')=='STALE' for f in S.get('fact_registry',[]))
    conflicts=sum(c.get('status')=='REVIEW_REQUIRED' for c in S.get('contradictions',[]))
    pending_skills=0
    try:
        reg=json.load(open(os.path.join(BASE,'data','self_improvement','skills.json'),encoding='utf-8'))
        pending_skills=sum(s.get('status') in {'CANDIDATE','TESTING','APPROVED'} for s in reg.get('skills',[]))
    except Exception: pass
    connector_fail=sum(c.get('status')=='ERROR' for c in S.get('connector_health',[]))
    unclassified=sum(x.get('status')=='NEW' for x in S.get('unified_inbox',[]))
    uncertain=sum((f.get('confidence') is not None and float(f.get('confidence',1))<0.7 and f.get('status','ACTIVE')=='ACTIVE') for f in S.get('fact_registry',[]))
    metrics={'open_decisions':open_dec,'overdue_waiting':overdue,'stale_facts':stale,'contradictions':conflicts,'pending_skill_changes':pending_skills,'connector_failures':connector_fail,'unclassified_inbox':unclassified,'low_confidence_facts':uncertain}
    score=max(0,100-(open_dec*3+overdue*4+stale*2+conflicts*8+pending_skills*2+connector_fail*10+unclassified+uncertain*2))
    lines=[f'# Trust Dashboard — {dt.datetime.now().isoformat(timespec="minutes")}',f'**Trust score: {score}/100**','', '| Signal | Count |','|---|---:|']
    for k,v in metrics.items(): lines.append(f'| {k} | {v} |')
    lines += ['', '## Judgment needed']
    if open_dec: lines.append(f'- {open_dec} decision request(s) require review.')
    if conflicts: lines.append(f'- {conflicts} contradiction(s) require an authoritative source or your decision.')
    if stale: lines.append(f'- {stale} fact(s) need re-verification before external use.')
    if connector_fail: lines.append(f'- {connector_fail} connector(s) are unhealthy; their data may be incomplete.')
    if not any((open_dec,conflicts,stale,connector_fail)): lines.append('- No trust-critical judgment item detected.')
    os.makedirs(os.path.dirname(OUT),exist_ok=True); open(OUT,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
    print(f'🛡️ trust score={score}/100 → reports/trust-dashboard-latest.md')
    return metrics,score
if __name__=='__main__': build()

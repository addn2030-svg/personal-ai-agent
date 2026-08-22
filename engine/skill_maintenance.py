# -*- coding: utf-8 -*-
"""Identify stale or underperforming ACTIVE skills without auto-retiring sensitive skills."""
import datetime as dt, json, os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG=os.path.join(BASE,'data','self_improvement','skills.json')
REPORT=os.path.join(BASE,'reports','skill-maintenance-latest.md')

def _date(v):
    try:return dt.datetime.fromisoformat(str(v)).date()
    except:return None

def scan(stale_days=60,min_uses=3,min_success=0.65):
    try:data=json.load(open(REG,encoding='utf-8'))
    except Exception:data={'skills':[]}
    today=dt.date.today(); flags=[]
    for s in data.get('skills',[]):
        if s.get('status')!='ACTIVE': continue
        m=s.get('metrics',{}); uses=int(m.get('uses',0)); successes=int(m.get('successes',0)); upd=_date(s.get('updated_at') or s.get('created_at'))
        reasons=[]
        if upd and (today-upd).days>=stale_days and uses==0: reasons.append(f'no use for {(today-upd).days} days')
        if uses>=min_uses and successes/uses<min_success: reasons.append(f'success rate {successes/uses:.0%}')
        if reasons: flags.append((s,reasons))
    os.makedirs(os.path.dirname(REPORT),exist_ok=True)
    lines=['# Skill maintenance review','']
    if not flags: lines.append('No ACTIVE skills require maintenance review.')
    for s,reasons in flags:
        lines.append(f'- **{s["id"]} {s["name"]}** ({s.get("risk_tier")}) — ' + '; '.join(reasons) + ' — recommend REVIEW, not automatic retirement.')
    open(REPORT,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
    print(f'🧠 skill maintenance flags: {len(flags)}')
    return flags
if __name__=='__main__': scan()

# -*- coding: utf-8 -*-
"""Source freshness + simple contradiction detector for provenance-aware facts."""
import datetime as dt, json, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event
DEFAULT_TTL={'price':90,'policy':90,'schedule':30,'contact':180,'general':365}

def _date(v):
    if not v: return None
    try: return dt.date.fromisoformat(str(v)[:10])
    except Exception: return None

def scan():
    st=Store(); S=st.rows_all(); today=dt.date.today(); facts=S.setdefault('fact_registry',[]); contradictions=[]; stale=[]
    grouped={}
    for f in facts:
        key=(f.get('subject'),f.get('predicate'))
        grouped.setdefault(key,[]).append(f)
        verified=_date(f.get('last_verified') or f.get('captured_at'))
        ttl=int(f.get('ttl_days') or DEFAULT_TTL.get(f.get('freshness_class','general'),365))
        if verified and (today-verified).days>ttl and f.get('status','ACTIVE')=='ACTIVE':
            f['freshness']='STALE'; stale.append(f.get('fact_id') or str(key))
        else: f['freshness']='CURRENT'
    for key,items in grouped.items():
        active=[x for x in items if x.get('status','ACTIVE')=='ACTIVE']
        values={json.dumps(x.get('value'),ensure_ascii=False,sort_keys=True,default=str) for x in active}
        if len(values)>1:
            cid=f"C-{len(contradictions)+1:03d}"; contradictions.append({'id':cid,'subject':key[0],'predicate':key[1],'fact_ids':[x.get('fact_id') for x in active],'status':'REVIEW_REQUIRED','detected_at':today.isoformat()})
    S['contradictions']=contradictions
    if stale or contradictions: st.commit(S,'source_governance_scan',stale=len(stale),contradictions=len(contradictions))
    if stale or contradictions: log_event('SOURCE_GOVERNANCE',stale=len(stale),contradictions=len(contradictions))
    print(f'📚 source governance: stale={len(stale)} contradictions={len(contradictions)}')
    return stale,contradictions
if __name__=='__main__': scan()

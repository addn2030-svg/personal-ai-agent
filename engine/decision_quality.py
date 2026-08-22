# -*- coding: utf-8 -*-
"""Schedule and score decision reviews: expected vs actual outcome becomes a learning signal."""
import datetime as dt, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

def _date(v):
    try:return dt.date.fromisoformat(str(v)[:10])
    except:return None

def scan():
    st=Store(); S=st.rows_all(); today=dt.date.today(); reviews=S.setdefault('decision_reviews',[]); existing={r.get('decision_key') for r in reviews}
    for i,d in enumerate(S.get('decisions',[])):
        key=str(d.get('id') or d.get('القرار') or f'decision-{i}')
        due=_date(d.get('تاريخ المراجعة') or d.get('review_date'))
        if due and due<=today and key not in existing:
            reviews.append({'review_id':f'DQR-{len(reviews)+1:03d}','decision_key':key,'due_date':due.isoformat(),'status':'DUE','expected':d.get('النتيجة المتوقعة') or d.get('expected_outcome') or '','actual':d.get('النتيجة الفعلية') or d.get('actual_outcome') or '','score':None,'lesson':''})
            existing.add(key)
    if any(r.get('status')=='DUE' for r in reviews): st.commit(S,'decision_quality_scan',due=sum(r.get('status')=='DUE' for r in reviews))
    print(f'🧭 decision reviews due: {sum(r.get("status")=="DUE" for r in reviews)}')

def score(review_id,score,actual='',lesson=''):
    st=Store(); S=st.rows_all(); r=next((x for x in S.setdefault('decision_reviews',[]) if x.get('review_id')==review_id),None)
    if not r: raise SystemExit('review not found')
    score=int(score)
    if not 0<=score<=100: raise SystemExit('score must be 0..100')
    r.update(status='COMPLETED',score=score,actual=actual or r.get('actual',''),lesson=lesson,completed_at=dt.date.today().isoformat())
    st.commit(S,'decision_quality_scored',review=review_id,score=score); log_event('DECISION_REVIEW_COMPLETED',review=review_id,score=score)
    print(f'✅ {review_id} scored {score}/100')
if __name__=='__main__':
    if len(sys.argv)>2 and sys.argv[1]=='score': score(sys.argv[2],sys.argv[3], ' '.join(sys.argv[4:]))
    else: scan()

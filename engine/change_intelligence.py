# -*- coding: utf-8 -*-
"""Detect material changes between state snapshots and write a concise change report."""
import datetime as dt, hashlib, json, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event
SNAP=os.path.join(BASE,'data','.last-state-snapshot.json')
REPORT=os.path.join(BASE,'reports','what-changed-latest.md')
WATCH=['tasks','projects','waiting_for','decision_requests','decisions','action_queue','okrs','knowledge_sources']

def _key(x):
    if not isinstance(x,dict): return str(x)
    for k in ('id','wid','action_id','project_id','المشروع','العنوان','القرار','source'):
        if x.get(k): return f'{k}:{x.get(k)}'
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,default=str,sort_keys=True).encode()).hexdigest()[:10]

def _load():
    try: return json.load(open(SNAP,encoding='utf-8'))
    except Exception: return {}

def detect():
    S=Store().rows_all(); old=_load(); changes=[]
    for sec in WATCH:
        now={_key(x):x for x in S.get(sec,[])}; prev={_key(x):x for x in old.get(sec,[])}
        for k in now.keys()-prev.keys(): changes.append((sec,'NEW',k,now[k]))
        for k in prev.keys()-now.keys(): changes.append((sec,'REMOVED',k,prev[k]))
        for k in now.keys()&prev.keys():
            if json.dumps(now[k],default=str,sort_keys=True,ensure_ascii=False)!=json.dumps(prev[k],default=str,sort_keys=True,ensure_ascii=False):
                changes.append((sec,'CHANGED',k,now[k]))
    os.makedirs(os.path.dirname(REPORT),exist_ok=True)
    lines=[f'# What changed — {dt.datetime.now().isoformat(timespec="minutes")}', '']
    if not changes: lines.append('No material tracked changes since the previous snapshot.')
    else:
        for sec,kind,k,obj in changes[:80]:
            status=obj.get('status') or obj.get('الحالة') or '' if isinstance(obj,dict) else ''
            lines.append(f'- **{kind}** `{sec}` — {k}' + (f' — {status}' if status else ''))
    open(REPORT,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
    snap={sec:[json.loads(json.dumps(x,default=str)) for x in S.get(sec,[])] for sec in WATCH}
    json.dump(snap,open(SNAP,'w',encoding='utf-8'),ensure_ascii=False,indent=1)
    if changes: log_event('CHANGE_INTELLIGENCE', count=len(changes))
    print(f'🔄 tracked changes: {len(changes)} → reports/what-changed-latest.md')
    return changes
if __name__=='__main__': detect()

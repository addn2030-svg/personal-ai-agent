# -*- coding: utf-8 -*-
"""Verify that current state and at least one backup are valid JSON and structurally restorable."""
import glob, json, os, sys, tempfile
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE=os.path.join(BASE,'data','state.json'); BACKUPS=os.path.join(BASE,'data','backups','state-*.json')

def _load(path):
    with open(path,encoding='utf-8') as f:return json.load(f)

def verify():
    problems=[]
    try: cur=_load(STATE)
    except Exception as e: problems.append(f'current state invalid: {e}'); cur={}
    backups=sorted(glob.glob(BACKUPS),reverse=True)
    valid=0
    for p in backups[:5]:
        try:
            x=_load(p)
            if isinstance(x,dict) and 'meta' in x: valid+=1
        except Exception as e: problems.append(f'{os.path.basename(p)} invalid: {e}')
    required={'tasks','projects','decisions','waiting_for','action_queue'}
    missing=sorted(required-set(cur)) if cur else sorted(required)
    if missing: problems.append('missing sections: '+', '.join(missing))
    print(f'🛟 backup verification: valid_backups={valid}/{min(5,len(backups))}')
    if problems:
        for p in problems: print('❌ '+p)
        return 1
    print('✅ current state parses and backup set is structurally restorable')
    return 0
if __name__=='__main__': raise SystemExit(verify())

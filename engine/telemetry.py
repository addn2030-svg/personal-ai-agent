# -*- coding: utf-8 -*-
"""Minimal operation telemetry: duration, cost estimate, success and component."""
import datetime as dt, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store

def record(component,operation,duration_ms,cost_sar=0.0,ok=True):
    st=Store(); S=st.rows_all(); rows=S.setdefault('telemetry',[])
    rows.append({'ts':dt.datetime.now().isoformat(timespec='seconds'),'component':component,'operation':operation,'duration_ms':int(duration_ms),'cost_sar':float(cost_sar),'ok':bool(ok)})
    S['telemetry']=rows[-1000:]
    st.commit(S,'telemetry_recorded',component=component,operation=operation)

def summary():
    S=Store().rows_all(); rows=S.get('telemetry',[])[-200:]
    total=sum(float(x.get('cost_sar',0)) for x in rows); failures=sum(not x.get('ok',True) for x in rows)
    avg=(sum(int(x.get('duration_ms',0)) for x in rows)/len(rows)) if rows else 0
    print(f'📈 operations={len(rows)} avg_latency={avg:.0f}ms cost={total:.2f} SAR failures={failures}')
if __name__=='__main__': summary()

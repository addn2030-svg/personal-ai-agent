# -*- coding: utf-8 -*-
"""Local connector health registry. Connectors report success/failure; trust dashboard reads it."""
import datetime as dt, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

def report(name,ok=True,error=''):
    st=Store(); S=st.rows_all(); rows=S.setdefault('connector_health',[]); row=next((x for x in rows if x.get('name')==name),None)
    if not row:
        row={'name':name}; rows.append(row)
    row.update(status='OK' if ok else 'ERROR',last_checked=dt.datetime.now().isoformat(timespec='seconds'))
    if ok: row['last_success']=row['last_checked']; row['last_error']=''
    else: row['last_error']=str(error)[:300]
    st.commit(S,'connector_health',connector=name,status=row['status']); log_event('CONNECTOR_HEALTH',connector=name,status=row['status'])
    print(f'{"✅" if ok else "❌"} {name}: {row["status"]}')

def summary():
    S=Store().rows_all(); rows=S.get('connector_health',[])
    for x in rows: print(f"{x.get('name')}: {x.get('status')} | success={x.get('last_success','—')} | error={x.get('last_error','—')}")
if __name__=='__main__':
    if len(sys.argv)>=3 and sys.argv[1]=='ok': report(sys.argv[2],True)
    elif len(sys.argv)>=3 and sys.argv[1]=='error': report(sys.argv[2],False,' '.join(sys.argv[3:]))
    else: summary()

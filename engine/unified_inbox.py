# -*- coding: utf-8 -*-
"""Normalize new inputs from Telegram/email/voice/files into one provenance-aware inbox queue."""
import datetime as dt, hashlib, json, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

def add(source,content,kind='TEXT',source_ref='',sensitive=False,metadata=None):
    st=Store(); S=st.rows_all(); rows=S.setdefault('unified_inbox',[])
    raw=f'{source}|{source_ref}|{content}'.encode('utf-8'); iid='IN-'+hashlib.sha256(raw).hexdigest()[:10].upper()
    if any(x.get('id')==iid for x in rows):
        print(f'↩️ duplicate ignored: {iid}'); return iid
    rec={'id':iid,'captured_at':dt.datetime.now().isoformat(timespec='seconds'),'source':source,'source_ref':source_ref,'kind':kind,'content':content,'sensitive':bool(sensitive),'metadata':metadata or {},'status':'NEW','classification':None,'next_action':None}
    rows.append(rec); st.commit(S,'unified_inbox_add',item=iid,source=source); log_event('UNIFIED_INBOX_CAPTURED',item=iid,source=source)
    print(f'📥 {iid} captured from {source}'); return iid

def classify(iid,classification,next_action=''):
    st=Store(); S=st.rows_all(); rec=next((x for x in S.setdefault('unified_inbox',[]) if x.get('id')==iid),None)
    if not rec: raise SystemExit('inbox item not found')
    allowed={'TASK','REQUEST','DECISION','WAITING_FOR','FACT','DOCUMENT','IDEA','CLINICAL_PRIVATE','IGNORE'}
    if classification not in allowed: raise SystemExit('invalid classification')
    rec.update(classification=classification,next_action=next_action,status='CLASSIFIED',classified_at=dt.datetime.now().isoformat(timespec='seconds'))
    if classification=='CLINICAL_PRIVATE': rec['content']='[REDACTED_FROM_PERSONAL_OS]'; rec['sensitive']=True
    st.commit(S,'unified_inbox_classify',item=iid,classification=classification); log_event('UNIFIED_INBOX_CLASSIFIED',item=iid,classification=classification)
    print(f'✅ {iid} → {classification}')
def listing():
    S=Store().rows_all(); rows=[x for x in S.get('unified_inbox',[]) if x.get('status')=='NEW']
    for x in rows[-30:]: print(x['id'],x['source'],x['kind'],x['content'][:100])
    print(f'NEW={len(rows)}')
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='add': add(sys.argv[2], ' '.join(sys.argv[3:]))
    elif len(sys.argv)>3 and sys.argv[1]=='classify': classify(sys.argv[2],sys.argv[3],' '.join(sys.argv[4:]))
    else: listing()

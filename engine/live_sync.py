# -*- coding: utf-8 -*-
"""Sync live sources into the provenance-aware Unified Inbox.
Read-only connectors only. External actions remain approval-gated elsewhere.
"""
from __future__ import annotations
import datetime as dt, os, re, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,BASE); sys.path.insert(0,os.path.join(BASE,'engine'))
from unified_inbox import add, classify
from connector_health import report

CLINICAL_HINTS=[r'patient',r'مريض',r'mrn',r'medical record',r'رقم الملف',r'diagnosis',r'تشخيص',r'clinic',r'عيادة']
REQUEST_HINTS=[r'please',r'request',r'kindly',r'أرجو',r'طلب',r'يرجى',r'مطلوب']
DECISION_HINTS=[r'decision',r'approve',r'approval',r'قرار',r'اعتماد',r'موافقة']
WAIT_HINTS=[r'waiting',r'follow.?up',r'pending',r'انتظار',r'متابعة',r'معلق']


def _classify_text(text):
    t=(text or '').lower()
    if any(re.search(p,t,re.I) for p in CLINICAL_HINTS): return 'CLINICAL_PRIVATE'
    if any(re.search(p,t,re.I) for p in DECISION_HINTS): return 'DECISION'
    if any(re.search(p,t,re.I) for p in WAIT_HINTS): return 'WAITING_FOR'
    if any(re.search(p,t,re.I) for p in REQUEST_HINTS): return 'REQUEST'
    return None


def sync_google():
    from connectors.google_workspace import gmail_recent,calendar_window,drive_recent,doctor
    health=doctor()
    for name,ok in health.items(): report(name,bool(ok))
    counts={'gmail':0,'calendar':0,'drive':0}
    for m in gmail_recent():
        text=f"Email: {m.get('subject','')}\nFrom: {m.get('from','')}\n{m.get('snippet','')}"
        iid=add('GMAIL',text,kind='EMAIL',source_ref=m['id'],metadata={'thread_id':m.get('thread_id'),'date':m.get('date'),'labels':m.get('labels',[])})
        c=_classify_text(text)
        if c: classify(iid,c,'Review in Chief of Staff')
        counts['gmail']+=1
    for e in calendar_window():
        text=f"Calendar: {e.get('summary')}\nStart: {e.get('start')}\n{e.get('description','')}"
        iid=add('CALENDAR',text,kind='EVENT',source_ref=e['id'],metadata={'start':e.get('start'),'end':e.get('end'),'updated':e.get('updated'),'url':e.get('htmlLink')})
        c=_classify_text(text)
        if c: classify(iid,c,'Review event context')
        counts['calendar']+=1
    for f in drive_recent():
        text=f"Drive document changed: {f.get('name')}\nModified: {f.get('modifiedTime')}"
        iid=add('GOOGLE_DRIVE',text,kind='DOCUMENT',source_ref=f['id'],metadata={'mimeType':f.get('mimeType'),'modifiedTime':f.get('modifiedTime'),'url':f.get('webViewLink')})
        classify(iid,'DOCUMENT','Review only if material to active work')
        counts['drive']+=1
    return counts


def sync_github():
    from connectors.github_live import recent_commits,open_prs,doctor
    doctor(); report('github',True); n=0
    for c in recent_commits():
        iid=add('GITHUB',f"Commit: {c['message']}",kind='CODE_CHANGE',source_ref=c['sha'],metadata={'date':c['date'],'url':c['url']})
        classify(iid,'FACT','Feed change intelligence')
        n+=1
    for p in open_prs():
        iid=add('GITHUB',f"Open PR #{p['number']}: {p['title']}",kind='PULL_REQUEST',source_ref=f"pr:{p['number']}",metadata={'updated_at':p['updated_at'],'url':p['url'],'draft':p['draft']})
        classify(iid,'REQUEST','Review merge/readiness if relevant')
        n+=1
    return n


def sync_telegram_health():
    from connectors.telegram_live import doctor
    doctor(); report('telegram',True); return 1


def run():
    results={}; failures=[]
    for name,fn in [('google',sync_google),('github',sync_github),('telegram',sync_telegram_health)]:
        try: results[name]=fn()
        except Exception as e:
            failures.append((name,str(e))); report(name,False,str(e))
    print('LIVE_SYNC',results)
    if failures:
        for n,e in failures: print(f'⚠️ {n}: {e}')
    return 0 if not failures else 2

if __name__=='__main__': raise SystemExit(run())

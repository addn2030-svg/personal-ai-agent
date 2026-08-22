# -*- coding: utf-8 -*-
"""Read-only Gmail/Calendar/Drive connector for AI OS v0.8.
Credentials remain local. Uses OAuth Desktop client secrets + cached user token.
"""
from __future__ import annotations
import base64, datetime as dt, os, re
from email.utils import parsedate_to_datetime

SCOPES=[
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
]
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRED=os.environ.get('GOOGLE_OAUTH_CLIENT_FILE', os.path.join(BASE,'secrets','google-oauth-client.json'))
TOKEN=os.environ.get('GOOGLE_OAUTH_TOKEN_FILE', os.path.join(BASE,'secrets','google-token.json'))


def _deps():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        return Credentials,Request,InstalledAppFlow,build
    except ImportError as e:
        raise RuntimeError('Install connector dependencies: pip install -r requirements-connectors.txt') from e


def credentials():
    Credentials,Request,InstalledAppFlow,_=_deps(); creds=None
    if os.path.exists(TOKEN): creds=Credentials.from_authorized_user_file(TOKEN,SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CRED): raise RuntimeError(f'Google OAuth client file missing: {CRED}')
            creds=InstalledAppFlow.from_client_secrets_file(CRED,SCOPES).run_local_server(port=0)
        os.makedirs(os.path.dirname(TOKEN),exist_ok=True)
        with open(TOKEN,'w',encoding='utf-8') as f: f.write(creds.to_json())
    return creds


def services():
    *_,build=_deps(); c=credentials()
    return build('gmail','v1',credentials=c,cache_discovery=False), build('calendar','v3',credentials=c,cache_discovery=False), build('drive','v3',credentials=c,cache_discovery=False)


def _header(headers,name):
    return next((h.get('value','') for h in headers if h.get('name','').lower()==name.lower()),'')


def gmail_recent(hours=72,max_results=25):
    gmail,_,_=services(); q=f'newer_than:{max(1,(hours+23)//24)}d -in:spam -in:trash -category:promotions'
    ids=gmail.users().messages().list(userId='me',q=q,maxResults=max_results).execute().get('messages',[])
    out=[]
    for row in ids:
        m=gmail.users().messages().get(userId='me',id=row['id'],format='metadata',metadataHeaders=['From','To','Subject','Date']).execute()
        h=m.get('payload',{}).get('headers',[]); date=_header(h,'Date')
        try: when=parsedate_to_datetime(date).isoformat()
        except Exception: when=date
        out.append({'id':m['id'],'thread_id':m.get('threadId'),'from':_header(h,'From'),'to':_header(h,'To'),'subject':_header(h,'Subject'),'date':when,'snippet':m.get('snippet',''),'labels':m.get('labelIds',[])})
    return out


def calendar_window(days_back=1,days_forward=14,max_results=50):
    _,cal,_=services(); now=dt.datetime.now(dt.timezone.utc)
    tmin=(now-dt.timedelta(days=days_back)).isoformat().replace('+00:00','Z'); tmax=(now+dt.timedelta(days=days_forward)).isoformat().replace('+00:00','Z')
    rows=cal.events().list(calendarId='primary',timeMin=tmin,timeMax=tmax,singleEvents=True,orderBy='startTime',maxResults=max_results).execute().get('items',[])
    out=[]
    for e in rows:
        out.append({'id':e['id'],'summary':e.get('summary','(untitled)'),'start':e.get('start',{}).get('dateTime') or e.get('start',{}).get('date'),'end':e.get('end',{}).get('dateTime') or e.get('end',{}).get('date'),'status':e.get('status'),'updated':e.get('updated'),'location':e.get('location',''),'description':(e.get('description') or '')[:800],'htmlLink':e.get('htmlLink','')})
    return out


def drive_recent(days=14,max_results=50):
    _,_,drive=services(); since=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)).isoformat().replace('+00:00','Z')
    q=f"trashed=false and modifiedTime > '{since}'"
    rows=drive.files().list(q=q,pageSize=max_results,orderBy='modifiedTime desc',fields='files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress),parents)').execute().get('files',[])
    return rows


def doctor():
    gmail,cal,drive=services()
    return {
      'gmail': bool(gmail.users().getProfile(userId='me').execute().get('emailAddress')),
      'calendar': bool(cal.calendarList().list(maxResults=1).execute().get('items') is not None),
      'drive': bool(drive.files().list(pageSize=1,fields='files(id)').execute().get('files') is not None),
    }

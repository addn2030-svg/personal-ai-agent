# -*- coding: utf-8 -*-
"""Safe Google Sheets read/search/update layer for Telegram intelligence."""
from __future__ import annotations
import json, os, re, urllib.request

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
SERVICE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
_SERVICE = None
PRIORITY_TABS = [
    "Projects","خطة الإنجاز والمهام","Smart_Inbox","Waiting_For","Blockers",
    "Executive_Brief","التطوير الشخصي","الهدف المالي E-S-B-I",
    "التحليل المالي المختصر","تعليمات تجاوز نقاط الضعف",
    "المصادر والتعلم العلمي","القرارات",
]
EXCLUDED_CONTEXT_TABS = {"Calc_Data","مدخلات الوكيل","محادثات الوكيل","حالة الوكيل"}

def configured():
    return bool((SHEET_ID and SERVICE_JSON) or (WEBHOOK_URL and WEBHOOK_SECRET))

def _webhook(action, **kwargs):
    payload={"secret":WEBHOOK_SECRET,"action":action,**kwargs}
    req=urllib.request.Request(WEBHOOK_URL,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type":"application/json"},method="POST")
    result=json.loads(urllib.request.urlopen(req,timeout=45).read().decode("utf-8"))
    if not result.get("ok"): raise RuntimeError("Sheets webhook: "+str(result.get("error","unknown")))
    return result

def _service():
    global _SERVICE
    if _SERVICE is not None: return _SERVICE
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info=json.loads(SERVICE_JSON)
    creds=service_account.Credentials.from_service_account_info(
        info,scopes=["https://www.googleapis.com/auth/spreadsheets"])
    _SERVICE=build("sheets","v4",credentials=creds,cache_discovery=False)
    return _SERVICE

def metadata():
    if WEBHOOK_URL and WEBHOOK_SECRET: return _webhook("metadata").get("sheets",[])
    data=_service().spreadsheets().get(spreadsheetId=SHEET_ID,fields="sheets.properties").execute()
    return [{"title":s["properties"]["title"],"sheetId":s["properties"]["sheetId"],
             "rows":s["properties"].get("gridProperties",{}).get("rowCount",0),
             "columns":s["properties"].get("gridProperties",{}).get("columnCount",0)}
            for s in data.get("sheets",[])]

def snapshot(max_rows=80,max_cols=16):
    max_rows=max(2,min(int(max_rows),150)); max_cols=max(2,min(int(max_cols),20))
    if WEBHOOK_URL and WEBHOOK_SECRET:
        return _webhook("snapshot",maxRows=max_rows,maxCols=max_cols).get("data",{})
    out={}
    sheets=metadata()
    by_title={s["title"]:s for s in sheets}
    ordered=[by_title[t] for t in PRIORITY_TABS if t in by_title]
    ordered += [s for s in sheets if s["title"] not in PRIORITY_TABS and s["title"] not in EXCLUDED_CONTEXT_TABS]
    for s in ordered[:18]:
        title=s["title"]
        values=_service().spreadsheets().values().get(
            spreadsheetId=SHEET_ID,range=f"'{title}'!A1:T{max_rows}").execute().get("values",[])
        if values: out[title]=[r[:max_cols] for r in values]
    return out

def search(query,max_results=25):
    query=(query or "").strip().lower()
    if not query: return []
    if WEBHOOK_URL and WEBHOOK_SECRET:
        return _webhook("search",query=query,maxResults=min(max_results,50)).get("results",[])
    results=[]
    for tab,rows in snapshot(150,20).items():
        for idx,row in enumerate(rows,1):
            if query in " | ".join(map(str,row)).lower():
                results.append({"sheet":tab,"row":idx,"values":row})
                if len(results)>=max_results:return results
    return results

def update_cell(sheet,a1,value):
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,5}",a1 or ""):
        raise ValueError("Use one cell such as B12")
    titles={s["title"] for s in metadata()}
    if sheet not in titles: raise ValueError("Unknown sheet: "+sheet)
    if WEBHOOK_URL and WEBHOOK_SECRET:
        return _webhook("update",sheet=sheet,range=a1,value=value,approved=True)
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,range=f"'{sheet}'!{a1}",valueInputOption="USER_ENTERED",
        body={"values":[[value]]}).execute()
    return {"ok":True,"sheet":sheet,"range":a1}

def compact_context(data=None,limit=12000):
    data=data if data is not None else snapshot()
    text=json.dumps(data,ensure_ascii=False,separators=(",",":"))
    return text[:limit]

# -*- coding: utf-8 -*-
"""Render a compact mobile-first control center from the local State Store."""
import html, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(BASE,"engine"))
from store import Store
OUT=os.path.join(BASE,"reports","control-center-latest.html")
def e(x): return html.escape(str(x or "—"))
def cards(title, items):
    body="".join(f'<div class="item">{e(x)}</div>' for x in items) or '<div class="muted">لا يوجد</div>'
    return f'<section><h2>{e(title)}</h2>{body}</section>'
def render():
    S=Store().rows_all()
    tasks=[t.get("العنوان") for t in S.get("tasks",[]) if t.get("الحالة")!="منجزة"][:6]
    approvals=[f"{a.get('action_id')} · {a.get('type')}" for a in S.get("action_queue",[]) if a.get("status")=="PENDING_APPROVAL"][:6]
    waiting=[f"{w.get('task') or w.get('item')} · {w.get('status')}" for w in S.get("waiting_for",[]) if w.get("status") in ("WAITING","OVERDUE")][:6]
    projects=[f"{p.get('المشروع')} · {p.get('الحالة')}" for p in S.get("projects",[]) if p.get("الحالة") in ("نشط","متوقف")][:6]
    energy=S.get("energy_log",[])[-1:] ; health=[f"طاقة {x.get('energy')}/10 · إرهاق {x.get('fatigue')}/10" for x in energy]
    okrs=[f"{o.get('id')} · {o.get('objective')}" for o in S.get("okrs",[]) if o.get("status")=="ACTIVE"][:4]
    reviews=[f"{r.get('concept_title')} · {r.get('status')}" for r in S.get("learning_reviews",[]) if r.get("status") in ("DUE","PRESENTED")][:4]
    fin=S.get("finance_ebsi") or {}; finance=[f"E-S-B-I loaded: {bool(fin)}"]
    body=''.join([cards('🎯 اليوم',tasks),cards('🛂 موافقات',approvals),cards('⏳ انتظار',waiting),cards('📁 مشاريع',projects),cards('💚 الصحة والطاقة',health),cards('🎯 OKR',okrs),cards('📚 التعلم',reviews),cards('💰 المالية',finance)])
    css='body{font-family:system-ui;margin:0;background:#f5f7fa;color:#17202a;direction:rtl}.top{position:sticky;top:0;background:#0f4c5c;color:white;padding:16px;font-weight:700}.wrap{padding:12px;max-width:760px;margin:auto}section{background:white;border-radius:16px;padding:12px;margin:10px 0;box-shadow:0 2px 10px #0000000d}h2{font-size:16px;margin:0 0 8px}.item{padding:10px;border-bottom:1px solid #edf0f2;font-size:14px}.item:last-child{border-bottom:0}.muted{color:#7b8794;padding:8px}'
    doc=f'<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style><div class="top">Abdulrahman AI OS · Control Center v0.5</div><div class="wrap">{body}</div></html>'
    os.makedirs(os.path.dirname(OUT),exist_ok=True); open(OUT,"w",encoding="utf-8").write(doc); print(OUT)
if __name__=="__main__": render()

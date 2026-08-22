# -*- coding: utf-8 -*-
"""Small regression suite for router/policy safety. Extend with real scenarios over time."""
import json, os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(BASE,"engine"))
from orchestrator import route
from permissions import authorize
CASES=[
 ("راجع لي حالة مشروع Life Pulse", "projects"),
 ("حلل اشتراكاتي الشهرية والتكاليف", "finance"),
 ("لدي مراجعة كتاب اليوم", "learning"),
 ("ابحث عن دراسة حول shoulder rehabilitation", "research"),
 ("مريض لديه ألم كتف بعد العملية", "clinical"),
 ("اكتب رسالة واتساب متابعة", "communications"),
 ("طاقة 4 إرهاق 8", "health"),
]
def run():
    results=[]; passed=0
    for text,expected in CASES:
        got=route(text)["agent"]; ok=got==expected; passed+=ok; results.append({"text":text,"expected":expected,"got":got,"pass":ok})
    safety=not authorize("clinical","send_message").allowed and not authorize("finance","pay").allowed and not authorize("executor","execute_approved",approved=False).allowed
    score=(passed+int(safety))/(len(CASES)+1)
    out={"passed":passed,"cases":len(CASES),"safety_gate":safety,"score":score,"results":results}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if score==1 else 1
if __name__=="__main__": raise SystemExit(run())

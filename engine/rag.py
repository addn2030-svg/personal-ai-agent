# -*- coding: utf-8 -*-
"""Lightweight provenance-first RAG without external dependencies.
Indexes approved local markdown/text plus knowledge_sources metadata. It deliberately excludes secrets, state backups and raw clinical uploads by default.
"""
import json, os, re, sys, hashlib
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX=os.path.join(BASE,"data","rag-index.json")
ALLOW_DIRS=("docs","materials","prompts","evaluation")
DENY_PARTS=(".env","token","secret","backups","audit.jsonl")

def chunks(text,size=900,overlap=120):
    text=re.sub(r"\s+"," ",text).strip(); out=[]; i=0
    while i < len(text):
        out.append(text[i:i+size]); i += max(1,size-overlap)
    return out

def build():
    docs=[]
    for d in ALLOW_DIRS:
        root=os.path.join(BASE,d)
        if not os.path.isdir(root): continue
        for dp,_,fs in os.walk(root):
            for fn in fs:
                p=os.path.join(dp,fn); rel=os.path.relpath(p,BASE)
                if any(x in rel.lower() for x in DENY_PARTS) or not fn.lower().endswith((".md",".txt")): continue
                try: txt=open(p,encoding="utf-8").read()
                except Exception: continue
                for n,c in enumerate(chunks(txt)):
                    docs.append({"id":hashlib.sha256((rel+str(n)).encode()).hexdigest()[:12],"source":rel,"chunk":n,"text":c})
    os.makedirs(os.path.dirname(INDEX),exist_ok=True)
    json.dump({"schema":"rag/1","documents":docs},open(INDEX,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    print(f"indexed {len(docs)} chunks -> data/rag-index.json")

def search(q,top=5):
    if not os.path.exists(INDEX): build()
    ds=json.load(open(INDEX,encoding="utf-8"))["documents"]
    terms=[x for x in re.findall(r"[\w\u0600-\u06ff]+",q.lower()) if len(x)>2]
    scored=[]
    for d in ds:
        t=d["text"].lower(); score=sum(t.count(x) for x in terms)
        if score: scored.append((score,d))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [{"score":s,"source":d["source"],"chunk":d["chunk"],"excerpt":d["text"][:500]} for s,d in scored[:top]]

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="build": build()
    else: print(json.dumps(search(" ".join(sys.argv[1:])),ensure_ascii=False,indent=2))

# -*- coding: utf-8 -*-
"""One command for v0.5 operational layer.
Runs existing manager full cycle, then rebuilds provenance RAG, health snapshot and mobile control center.
"""
import os, subprocess, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run(name,*args):
    p=subprocess.run([sys.executable,os.path.join(BASE,"engine",name),*args],capture_output=True,text=True)
    print(p.stdout.strip())
    if p.returncode:
        print(p.stderr.strip()); raise SystemExit(p.returncode)

def main():
    run("manager.py","full")
    run("rag.py","build")
    run("observability.py")
    run("control_center.py")
    run("evaluate.py")
    print("✅ AI OS v0.5 cycle complete")
if __name__=="__main__": main()

# -*- coding: utf-8 -*-
"""AI OS v0.6 cycle: v0.5 operations + reflection + self-review.
This cycle never auto-executes external effects and never auto-activates sensitive skills.
"""
import os, subprocess, sys

BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run():
    steps=[
        [sys.executable, os.path.join(BASE,"engine","v05_cycle.py")],
        [sys.executable, os.path.join(BASE,"engine","reflection_engine.py"),"reflect"],
        [sys.executable, os.path.join(BASE,"engine","self_review.py")],
    ]
    for cmd in steps:
        r=subprocess.run(cmd,capture_output=True,text=True)
        print(r.stdout.strip())
        if r.returncode:
            print(r.stderr.strip()); return r.returncode
    print("✅ AI OS v0.6 cycle complete — operational state + learning reflection + review generated")
    return 0

if __name__=="__main__": raise SystemExit(run())

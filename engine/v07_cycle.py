# -*- coding: utf-8 -*-
"""AI OS v0.7 operational trust cycle.
Runs v0.6, then change detection, source governance, decision review, skill maintenance,
backup verification and the trust dashboard. No external action is auto-executed.
"""
import os, subprocess, sys, time
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run():
    steps=[
        ('v0.6 core',[sys.executable,os.path.join(BASE,'engine','v06_cycle.py')]),
        ('changes',[sys.executable,os.path.join(BASE,'engine','change_intelligence.py')]),
        ('sources',[sys.executable,os.path.join(BASE,'engine','source_governance.py')]),
        ('decisions',[sys.executable,os.path.join(BASE,'engine','decision_quality.py')]),
        ('skills',[sys.executable,os.path.join(BASE,'engine','skill_maintenance.py')]),
        ('backup',[sys.executable,os.path.join(BASE,'engine','backup_verify.py')]),
        ('trust',[sys.executable,os.path.join(BASE,'engine','trust_dashboard.py')]),
    ]
    failures=[]
    for name,cmd in steps:
        t=time.perf_counter(); r=subprocess.run(cmd,capture_output=True,text=True); ms=int((time.perf_counter()-t)*1000)
        if r.stdout.strip(): print(r.stdout.strip())
        if r.returncode:
            failures.append(name); print(r.stderr.strip())
        try:
            subprocess.run([sys.executable,os.path.join(BASE,'engine','telemetry.py')],capture_output=True,text=True)
        except Exception: pass
        print(f'  ↳ {name}: {ms} ms')
    print('✅ AI OS v0.7 trust cycle complete' if not failures else '⚠️ v0.7 completed with failures: '+', '.join(failures))
    return 0 if not failures else 1
if __name__=='__main__': raise SystemExit(run())

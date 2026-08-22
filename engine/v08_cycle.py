# -*- coding: utf-8 -*-
"""AI OS v0.8: live-source sync followed by v0.7 trust cycle."""
import os, subprocess, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run():
    sync=subprocess.run([sys.executable,os.path.join(BASE,'engine','live_sync.py')],capture_output=True,text=True)
    if sync.stdout.strip(): print(sync.stdout.strip())
    if sync.returncode not in (0,2):
        print(sync.stderr.strip()); return sync.returncode
    core=subprocess.run([sys.executable,os.path.join(BASE,'engine','v07_cycle.py')],capture_output=True,text=True)
    if core.stdout.strip(): print(core.stdout.strip())
    if core.returncode:
        print(core.stderr.strip()); return core.returncode
    print('✅ AI OS v0.8 complete — live sources synced, then trust/change intelligence refreshed')
    return 0
if __name__=='__main__': raise SystemExit(run())

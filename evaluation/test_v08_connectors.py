# -*- coding: utf-8 -*-
"""Offline smoke tests for v0.8 connector architecture."""
import os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,BASE); sys.path.insert(0,os.path.join(BASE,'engine'))

from live_sync import _classify_text
from connectors import google_workspace, github_live, telegram_live

assert _classify_text('Please approve this request') == 'DECISION'
assert _classify_text('متابعة الطلب المعلق') == 'WAITING_FOR'
assert _classify_text('Patient clinic diagnosis') == 'CLINICAL_PRIVATE'
assert _classify_text('يرجى إرسال التقرير') == 'REQUEST'
assert _classify_text('ordinary newsletter') is None
assert hasattr(google_workspace,'gmail_recent') and hasattr(google_workspace,'calendar_window') and hasattr(google_workspace,'drive_recent')
assert hasattr(github_live,'recent_commits') and hasattr(telegram_live,'doctor')
print('✅ v0.8 connector smoke tests passed (offline)')

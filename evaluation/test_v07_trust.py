# -*- coding: utf-8 -*-
"""Smoke tests for v0.7 trust/change layer. Uses temporary files where possible."""
import os, sys, tempfile, json
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(BASE,'engine'))

def test_imports():
    import change_intelligence, source_governance, decision_quality, connector_health, telemetry, backup_verify, skill_maintenance, unified_inbox, trust_dashboard
    assert callable(change_intelligence.detect)
    assert callable(source_governance.scan)
    assert callable(decision_quality.scan)
    assert callable(trust_dashboard.build)

def test_source_constants():
    import source_governance
    assert source_governance.DEFAULT_TTL['price'] <= source_governance.DEFAULT_TTL['general']

def test_no_sensitive_autowrite_contract():
    import unified_inbox
    assert 'CLINICAL_PRIVATE' in unified_inbox.classify.__code__.co_consts

if __name__=='__main__':
    test_imports(); test_source_constants(); test_no_sensitive_autowrite_contract(); print('✅ v0.7 smoke tests passed')

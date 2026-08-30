# -*- coding: utf-8 -*-
"""Normalize new inputs into one provenance-aware inbox queue."""
import datetime as dt
import hashlib
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

PRIVATE_PLACEHOLDER = '[REDACTED_FROM_PERSONAL_OS]'


def add(source, content, kind='TEXT', source_ref='', sensitive=False, metadata=None):
    """Capture one source item idempotently and safely under concurrent writers."""
    raw = f'{source}|{source_ref}|{content}'.encode('utf-8')
    iid = 'IN-' + hashlib.sha256(raw).hexdigest()[:10].upper()
    persisted_content = PRIVATE_PLACEHOLDER if sensitive else content
    st = Store()

    def mutate(state):
        rows = state.setdefault('unified_inbox', [])
        if any(x.get('id') == iid for x in rows):
            return False, False
        rows.append({
            'id': iid,
            'captured_at': dt.datetime.now().isoformat(timespec='seconds'),
            'source': source,
            'source_ref': source_ref,
            'kind': kind,
            'content': persisted_content,
            'sensitive': bool(sensitive),
            'metadata': metadata or {},
            'status': 'NEW',
            'classification': None,
            'classifications': [],
            'linked_record_ids': [],
            'relation_group_id': None,
            'next_action': None,
        })
        return True, True

    created = st.transaction(mutate, 'unified_inbox_add', item=iid, source=source)
    if created:
        log_event('UNIFIED_INBOX_CAPTURED', item=iid, source=source)
        print(f'📥 {iid} captured from {source}')
    else:
        print(f'↩️ duplicate ignored: {iid}')
    return iid


def classify(iid, classification, next_action=''):
    """Legacy single-classification API retained for backward compatibility."""
    allowed = {'TASK', 'REQUEST', 'DECISION', 'WAITING_FOR', 'FACT', 'DOCUMENT',
               'IDEA', 'CLINICAL_PRIVATE', 'IGNORE'}
    if classification not in allowed:
        raise SystemExit('invalid classification')
    st = Store()

    def mutate(state):
        rec = next((x for x in state.setdefault('unified_inbox', []) if x.get('id') == iid), None)
        if not rec:
            raise SystemExit('inbox item not found')
        rec.update(
            classification=classification,
            classifications=[classification],
            next_action=next_action,
            status='CLASSIFIED',
            classified_at=dt.datetime.now().isoformat(timespec='seconds'),
        )
        if classification == 'CLINICAL_PRIVATE':
            rec['content'] = PRIVATE_PLACEHOLDER
            rec['sensitive'] = True
        return True, True

    st.transaction(mutate, 'unified_inbox_classify', item=iid, classification=classification)
    log_event('UNIFIED_INBOX_CLASSIFIED', item=iid, classification=classification)
    print(f'✅ {iid} → {classification}')


def classify_and_record(iid, content, kind='TEXT', source='TELEGRAM', source_ref=''):
    """WO-8: extract every confident intent and atomically create linked records."""
    from multi_intent import record_intents

    result = record_intents(
        iid,
        content,
        kind=kind,
        source=source,
        source_ref=source_ref,
    )
    if result.get('classifications'):
        log_event(
            'UNIFIED_INBOX_MULTI_CLASSIFIED',
            item=iid,
            classifications=result.get('classifications'),
            record_count=result.get('record_count', 0),
            relation_group_id=result.get('relation_group_id'),
        )
        print(f"✅ {iid} → {','.join(result['classifications'])}")
    return result


def listing():
    state = Store().rows_all()
    rows = [x for x in state.get('unified_inbox', []) if x.get('status') == 'NEW']
    for x in rows[-30:]:
        print(x['id'], x['source'], x['kind'], str(x.get('content', ''))[:100])
    print(f'NEW={len(rows)}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'add':
        add(sys.argv[2], ' '.join(sys.argv[3:]))
    elif len(sys.argv) > 3 and sys.argv[1] == 'classify':
        classify(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))
    else:
        listing()

# Production Hardening Plan — 2026-08-26

Status: implementation branch. No Postgres. No job queue.

## Final decisions

1. **Telegram transport** — production is webhook-only. CI rejects production calls to polling APIs or a direct polling launcher. `connectors/telegram_bot.py` is now a guarded compatibility entrypoint: `run()` raises unless `AI_OS_ALLOW_POLLING=1`. The implementation is retained in `telegram_bot_legacy.py`; Railway must not define the opt-in variable.
2. **CI** — Python 3.12 exactly, existing `scripts/smoke_test.sh` retained, plus unit tests, source contract checks, transport guard, and obvious-secret scan.
3. **Sheets gateway** — source contract and live contract are separate gates. `ping` returns the deployed action set. After Apps Script deployment run `python scripts/check_gateway_contract.py --live`; deployment is rejected on drift.
4. **StateStore concurrency** — read-modify-write is serialized by one in-process lock plus a cross-process file lock. Legacy optimistic version detection remains as a secondary guard.
5. **Volume/bootstrap/migrate** — production startup fails closed on missing/empty/wrong-schema state. Migration first copies `master-sheet.xlsx` to `AI_OS_DATA_DIR/30-state-backups/`, then verifies source-row counts and state version.
6. **Manager markers** — stored inside StateStore under `manager_markers`; no separate `.manager-markers.json` is used by the new manager loop.
7. **Source of truth** — StateStore is operational truth. Sheets is both a human-input surface and a machine projection, but not for the same ownership field at the same time.
8. **Retry/idempotency** — webhook append retries carry a stable idempotency key. Apps Script also deduplicates the stable IDs of `مدخلات الوكيل` and `محادثات الوكيل` under a script lock.
9. **APPOINTMENT** — classified in webhook runtime as `APPOINTMENT` and persisted in StateStore/unified inbox as `NEEDS_CONFIRMATION`. This phase does not write Calendar events. Calendar mutation stays behind `/remind` → preview → `/confirm_event` and a staging Calendar.
10. **Staging** — must use a separate Railway service, separate persistent volume, separate Telegram bot/webhook, separate Apps Script deployment version/endpoint, staging Google Sheet, staging Calendar, and isolated Bedrock model/budget settings. Never mount the production volume in staging.
11. **PR #7** — do not merge. Preserve only useful test intent; `/b` is handled by the production runtime alias. Close with a comment explaining why the PR was superseded.

## Telegram polling compatibility layout

- `connectors/telegram_bot.py`: guarded entrypoint and import compatibility layer.
- `connectors/telegram_bot_legacy.py`: existing command/business implementation; never launch directly in production.
- `connectors/telegram_webhook.py`: production transport.
- Polling is an explicit local-only escape hatch and requires `AI_OS_ALLOW_POLLING=1`.

## Sheets ↔ StateStore ownership

| Direction | Owner/content | Rule |
|---|---|---|
| Sheets → StateStore | human-edited rows | import/reconcile explicitly; never overwrite a newer machine-owned operational field silently |
| StateStore → Sheets | machine-created operational records and dashboard metrics | idempotent projection; Sheets is not used as the authoritative read-back for those fields |

Temporary `/brief` rule implemented in this branch: operational sections come from StateStore; Sheets supplies bounded human/manual evidence and the dashboard projection. Any conflict must be surfaced, not silently merged.

## Phase order

### Phase 1 — transport + CI + contract
- active `.github/workflows/ci.yml`
- production webhook static guard
- runtime polling guard
- Apps Script `ping` source/live handshake
- retain smoke test

### Phase 2 — persistence prerequisite
- Railway volume at `AI_OS_DATA_DIR`
- workbook backup
- migration
- strict validation
- version persistence across redeploys

### Phase 3 — writer safety
- Store transaction lock
- manager and unified-inbox mutations use transaction
- manager markers in StateStore
- concurrency acceptance test

### Phase 4 — idempotency + source ownership
- idempotent Sheets appends
- StateStore-first `/brief`
- document two-way ownership/reconciliation

### Phase 5 — manager expansion and classification
- run Manager loop only after Phases 1–4 pass
- `APPOINTMENT` enters StateStore as `NEEDS_CONFIRMATION`
- Calendar write remains a separate release/gate

### Phase 6 — data repair (WO-10 only here)
- remove known duplicate/malformed rows only after writer safety and idempotency are deployed
- record before/after counts and repair decisions

## Acceptance gates before merge/deploy

- `python -m unittest discover -s tests -p 'test_*.py' -v`
- `bash scripts/smoke_test.sh`
- `python scripts/check_production_guards.py`
- `python scripts/check_gateway_contract.py`
- unit test: `telegram_bot.run()` raises without `AI_OS_ALLOW_POLLING=1`
- unit test: APPOINTMENT persists as `NEEDS_CONFIRMATION`
- after staging Apps Script deployment: `python scripts/check_gateway_contract.py --live`
- concurrency test: N increments → final counter exactly N and N commit-audit lines
- migration: persisted source-row count equals workbook source-row count
- two staging redeploys: StateStore version increases rather than resetting
- restart Manager after a completed full cycle: no duplicate same-day catch-up
- Telegram production observation: zero HTTP 409 conflicts for 24 hours

## Deployment rule for Apps Script

Update the existing deployment with a **new version**. Do not create parallel production deployments. Staging has its own isolated deployment endpoint. The live `ping` action set must equal `connectors.gateway_contract.EXPECTED_ACTIONS` before promotion.

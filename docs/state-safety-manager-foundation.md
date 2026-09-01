# State Safety + Manager Foundation

Scope of this branch is intentionally narrow.

## Included
- Serialize StateStore read-modify-write in-process and cross-process.
- Preserve optimistic version checks for legacy callers.
- Copy backups instead of moving the active state file away before replacement.
- Persist Manager loop markers inside StateStore instead of a separate repository-local marker file.
- Convert Manager fast-cycle and decision mutations to Store.transaction().
- Add regression tests for exact concurrent increments and persistent Manager markers.
- Add these files/tests to the existing Production Model Router CI workflow.

## Explicitly not included
- No production Manager startup.
- No change to Telegram webhook transport.
- No Calendar worker changes.
- No Apps Script changes.
- No FULL-cycle activation.
- No Thinking v1 / prompt changes.
- No merge until main branch protection and required CI are enabled.

## Activation sequence after merge
1. Verify AI_OS_DATA_DIR points to the Railway persistent volume.
2. Verify state version survives redeploys.
3. Add Manager FAST-only startup behind an environment flag in a separate PR.
4. Observe heartbeat and FAST cycle before enabling any broader Manager behavior.

# Runtime, Time, and Project Memory — Production Contract

## 1) Time

The automation scheduler uses `MANAGER_TIMEZONE` and defaults to:

```text
Asia/Riyadh
```

The canonical schedule currently includes:

- Daily morning brief: 06:45
- Focus block: 07:30
- Supervisor close (Sun–Thu): 16:00
- Audio digest: 20:30
- Weekly operations review: Sunday 07:15

The production webhook worker must call `scheduler.dispatch_due()` on every proactive cycle. This is wired in `connectors/proactive_worker.py`.

Recommended Railway variable:

```text
MANAGER_TIMEZONE=Asia/Riyadh
```

## 2) Persistent runtime state

Railway containers are ephemeral. The StateStore, automation deduplication ledger, proactive configuration, and open-loop state must live on a mounted volume.

Required Railway setup:

```text
Volume mount: /data
AI_OS_DATA_DIR=/data
```

Without this, state can reset after deploy/restart even when the code is correct.

## 3) Durable project memory in Google Drive

The production runtime exposes:

```text
/memory
/memory_status
/update_memory achievement || next step || optional decision
/confirm_memory TOKEN
```

Natural-language alias:

```text
حدث ذاكرة المشروع: achievement || next step || optional decision
```

Default Google Docs:

```text
Status.md   = 1zs5GJ5Kw9TgHpNAfTOo37Fo7TnQYXejgquXOtHTQCuE
Progress.md = 1WolECTe7H3L7ZMRrsjrVzhZ7twXi_ZixvQgJkAu9G3w
Decision.md = 1g_Vz042YHXlCKwDJnat-WVEKVhPp6oNQ4Be-7ZC3BJA
```

Optional overrides:

```text
PROJECT_MEMORY_STATUS_DOC_ID=...
PROJECT_MEMORY_PROGRESS_DOC_ID=...
PROJECT_MEMORY_DECISION_DOC_ID=...
PROJECT_MEMORY_APPROVAL_TTL_SECONDS=900
```

The three Docs must be shared with the `client_email` inside `GOOGLE_SERVICE_ACCOUNT_JSON` as Editor.

Writes are guarded:

1. `/update_memory ...` creates a preview only.
2. `/confirm_memory TOKEN` performs the write.
3. Each confirmed update carries an idempotency marker (`[memory:TOKEN]`) so a retry cannot append a duplicate entry.
4. Inputs that look like secrets or patient identifiers are rejected.

## 4) Post-deploy acceptance

From Telegram:

```text
/proactive
/schedule
/memory_status
/memory
```

Then run one harmless memory update:

```text
/update_memory Runtime timing and Drive memory connected || Verify persistence after redeploy
```

Copy the generated token and send:

```text
/confirm_memory TOKEN
```

Finally redeploy Railway and verify:

- `/proactive` does not show a persistence warning.
- `/memory` still contains the confirmed update.
- The next scheduled job creates only one draft (no duplicate after restart).

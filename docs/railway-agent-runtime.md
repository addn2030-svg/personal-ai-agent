# Railway Agent Runtime — Memory, separated Sheets, and Gemini API

For the complete migration checklist, environment-variable inventory, safe transfer
commands, and the 24-hour expiry diagnosis, see [`docs/railway-migration.md`](railway-migration.md).

## Entrypoint invocation (crash-loop guard)

The container entrypoint is `connectors/telegram_webhook_runtime_memory.py`. It
must be started as a **module**:

```text
python3 -u -m connectors.telegram_webhook_runtime_memory
```

Running it as a script (`python3 connectors/telegram_webhook_runtime_memory.py`)
puts `/app/connectors` on `sys.path` instead of `/app`, so
`from connectors import project_memory` fails with
`ModuleNotFoundError: No module named 'connectors'` and the deploy crash-loops
forever. The Dockerfile already sets `PYTHONPATH=/app` and uses the `-m` form,
and the module bootstraps `sys.path` from `__file__` as a second line of defence.

If you override the start command in Railway, keep the `-m` form.

## Required Railway variables

### Core
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ALLOWED_CHAT_ID
- AI_MODEL_PROVIDER=gemini
- AI_CLINICAL_PROVIDER=gemini
- GEMINI_API_KEY=<secret>
- GEMINI_MODEL=google/gemini-3.7-flash

### Persistent state ⚠️ REQUIRED — deploy will lose all state without it

Attach a Railway Volume mounted at `/data`, then set:
- **AI_OS_DATA_DIR=/data** (REQUIRED — without a mounted volume every redeploy
  factory-resets the proactive engine: cfg overrides, standing orders, pause
  state, the `last_full` marker, the `automation_runs` deduplication ledger,
  and the open-loops ledger all live in `data/state.json` which is
  git-ignored runtime state). The worker logs a loud startup ⚠️ warning and
  the `/proactive` diagnostics page surfaces a `persistence` block when this
  is missing — but code cannot create a persistent disk for you.
- AGENT_MEMORY_TURNS=10
- AGENT_CONTEXT_CHARS=14000

### Google Sheets
- GOOGLE_SERVICE_ACCOUNT_JSON=<complete service account JSON>
- GOOGLE_SHEET_ID=<operational workbook ID>
- CLINICAL_SHEET_ID=1Te-dD6B9USOzURbTjMoZQgYtDeoygwR6QRGeHHGAzaQ
- CLINICAL_SHEET_TAB=<approved restricted tab name, recommended>

Share both workbooks with the service-account email as Editor. Clinical intake and
conversation rows use the dedicated clinical ID and never fall back to
`GOOGLE_SHEET_ID`; the connector resolves the first existing tab only when
`CLINICAL_SHEET_TAB` is not set.

### Google Calendar actions and Telegram reminders
Recommended on Railway: use the same service account, then:
- Share the target Google Calendar with the service-account email and grant
  **Make changes to events**.
- Set `GOOGLE_CALENDAR_ID` to the calendar ID shown in Google Calendar
  Settings -> Integrate calendar. Do not use `primary` with a service account.
- Optional: set `GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON`; otherwise the runtime
  reuses `GOOGLE_SERVICE_ACCOUNT_JSON`.
- Keep `MANAGER_TIMEZONE=Asia/Riyadh`.

OAuth alternative: the connector requests `calendar.events`. An older cached
read-only token cannot gain that scope by refresh; delete/recreate the token once
and complete Google consent again.

Calendar safety:
- `/remind` creates a preview only.
- `/confirm_event TOKEN` performs the insert and returns Event ID + link.
- `/cancel_event EVENT_ID` creates a delete preview.
- `/confirm_cancel TOKEN` performs deletion.
- The polling runtime checks due reminders every minute and records sent alerts
  in the persistent data directory to prevent duplicates.

### Telegram input is text-only
Telegram voice/audio transcription is disabled in the production runtime. Do not
configure S3 or Amazon Transcribe for this bot. Voice/audio updates receive a
text-only response and are not sent to any transcription provider or model.
## Runtime flow

Telegram -> privacy/category -> local Unified Inbox -> bounded conversation
memory -> state + lexical knowledge retrieval -> Gemini API -> Telegram ->
Google Sheets audit.

Voice/audio is intentionally outside the runtime; resend the request as text.

## Health commands
- /selftest
- /ai_status
- /storage_status
- /clinical_status

Clinical content is tagged CLINICAL_PRIVATE; email, Saudi mobile, MRN and similar
identifiers are redacted before Sheets logging. Human review remains required.

# Railway Agent Runtime — Memory, Sheets, Bedrock and Voice

## Required Railway variables

### Core
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ALLOWED_CHAT_ID
- AWS_BEARER_TOKEN_BEDROCK
- AWS_REGION=us-east-1
- BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6

### Persistent state
Attach a Railway Volume mounted at `/data`, then set:
- AI_OS_DATA_DIR=/data
- AGENT_MEMORY_TURNS=10
- AGENT_CONTEXT_CHARS=14000

### Google Sheets
- GOOGLE_SERVICE_ACCOUNT_JSON=<complete service account JSON>
- GOOGLE_SHEET_ID=1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc

Share the workbook with the service-account email as Editor.

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

### Automatic timing (morning brief + periodic sweeps)

The image has no cron daemon, so the schedule runs as a worker thread inside the
webhook process. Defaults are already correct; only tune these when needed:
- `AIOS_TIMING_ENABLED` (default `1`) — master switch for the whole timing engine.
- `AIOS_TIMING_WORKER` (default `1`) — the in-container thread only.
- `TIMING_BRIEF_AT` (06:30), `TIMING_SWEEP_INTERVAL_HOURS` (3),
  `TIMING_REVIEW_AT` (07:00), `TIMING_REVIEW_WEEKDAY` (6 = Sunday),
  `TIMING_TICK_SECONDS` (300), `TIMING_PUSH` (1), `TIMING_RETRY_MINUTES` (20).
- Keep `MANAGER_TIMEZONE=Asia/Riyadh`: due times are computed in that zone, not in
  the container clock.

Timing output stays drafts: the proactive sweep and the automation scheduler only
enqueue `PENDING_APPROVAL` rows; the single external channel is the same proactive
alert chat. Verify with `GET /health` -> `automatic_timing`, or from the phone:
`/timing` (schedule card), `/timing_run brief` (run one job now), `/review`
(weekly acceptance review). Full reference: `docs/automatic-timing.md`.

If you deploy on a host that has cron, prefer the crontab entry instead:
`bash autostart/cron/install.sh` (writes a `*/5 * * * * .../scripts/aios-timing.sh tick`
line plus an `@reboot` catch-up tick).

### Voice transcription
The Bedrock bearer key does not authorize S3 or Transcribe. Use a dedicated
least-privilege IAM principal:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_S3_AUDIO_BUCKET
- AWS_TRANSCRIBE_LANGUAGE_CODE=ar-SA (or auto)
- AWS_TRANSCRIBE_TIMEOUT_SECONDS=120

Minimum permissions should be limited to:
- s3:PutObject, s3:GetObject, s3:DeleteObject on
  arn:aws:s3:::BUCKET/telegram-audio/*
- transcribe:StartTranscriptionJob
- transcribe:GetTranscriptionJob
- transcribe:DeleteTranscriptionJob

The runtime uploads audio with S3 AES256 encryption and deletes both the S3
object and transcription job in a finally block.

## Runtime flow

Telegram -> privacy/category -> local Unified Inbox -> bounded conversation
memory -> state + lexical knowledge retrieval -> Claude/Bedrock -> Telegram ->
Google Sheets audit.

Voice adds: Telegram getFile -> temporary local file -> private S3 -> Amazon
Transcribe -> delete temporary objects -> normal text flow.

## Health commands
- /selftest
- /ai_status
- /storage_status
- /timing (automatic-timing card), /timing_run [brief|sweep|review], /review [days]
- `python3 engine/timing.py verify` on the container prints a 13-point proof of life
  (flags, clock vs schedule, today's pulse, push channel, installer, data dir).
- Proactive guardrails are tunable from state without redeploying:
  `python3 engine/proactive.py config --quiet 22:00-06:30 --max-alerts 6`.

Clinical content is tagged CLINICAL_PRIVATE; email, Saudi mobile, MRN and similar
identifiers are redacted before Sheets logging. Human review remains required.

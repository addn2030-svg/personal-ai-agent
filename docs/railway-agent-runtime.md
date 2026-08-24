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

Clinical content is tagged CLINICAL_PRIVATE; email, Saudi mobile, MRN and similar
identifiers are redacted before Sheets logging. Human review remains required.

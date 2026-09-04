# Google Drive project memory

The Telegram agent can read and update the project-memory Google Docs through
the existing Google service account.

## Commands

- `/memory`: read bounded excerpts from Status, Progress, and Decision.
- `/memory_status`: show whether Google credentials are configured.
- `/update_memory achievement || next step || optional decision`: create a preview.
- `/confirm_memory TOKEN`: apply the preview within 15 minutes.
- Arabic phrase `حدث ذاكرة المشروع ...` is an alias for `/update_memory`.

No write happens without the confirmation token. Progress and Status are
updated for every approved change; Decision is updated only when an explicit
decision is provided.

## Railway configuration

The code uses `GOOGLE_SERVICE_ACCOUNT_JSON`, already used by the direct Sheets
connector. Share the three Google Docs with that service-account email as
Editor. Optional variables override the built-in document IDs:

- `PROJECT_MEMORY_STATUS_DOC_ID`
- `PROJECT_MEMORY_PROGRESS_DOC_ID`
- `PROJECT_MEMORY_DECISION_DOC_ID`

The built-in IDs point to the current project-memory documents in Google Drive.

## Safety

- GitHub remains the source of truth for code.
- Inputs containing common secret or patient-identifier labels are rejected.
- Pending previews live in memory for 15 minutes and disappear after restart.
- Updates are append-only in this first version; old progress and decisions are
  never deleted.
- If the Google account cannot open a document, the command fails explicitly
  and does not claim success.

## Deployment verification

1. Share all three Docs with the service-account email as Editor.
2. Deploy the branch to staging or a safe Railway preview.
3. Run `/memory_status`.
4. Run `/memory`.
5. Run `/update_memory test memory connection || verify Drive readback`.
6. Inspect the preview, then run the exact `/confirm_memory TOKEN`.
7. Confirm the new entry appears in Progress and Status.

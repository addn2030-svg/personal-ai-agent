# Railway migration runbook

This repository is already packaged for a long-running Railway deployment. The
Dockerfile starts the production Telegram webhook as a module:

```text
python3 -u -m connectors.telegram_webhook_runtime_memory
```

Do **not** replace that with the old polling command. The webhook binds to
`0.0.0.0:$PORT`, exposes `/health`, and configures Telegram's webhook on startup.

> **Terminology:** “variables” means environment variables. Do not put their
> values in GitHub, this repository, or a chat message.

## What must be transferred

| Item | Transfer method | Why |
|---|---|---|
| Source code | Connect Railway to `addn2030-svg/personal-ai-agent` and deploy the desired branch | Railway builds the committed Dockerfile |
| Environment variables | Railway service → **Variables**, or the Railway CLI | Tokens and configuration are injected at runtime |
| Google/AWS/Telegram permissions | Re-create or verify them at each provider | A variable alone does not grant access to a Sheet, Calendar, bucket, or bot |
| Runtime state | Railway Volume or a one-time state backup/restore | `data/state.json`, audit logs, ledgers, and snapshots are not environment variables |
| Local OAuth files | Do not copy local paths unless the file is mounted separately | A path such as `secrets/google-token.json` does not exist in the container by default |

If the current 24-hour environment is a temporary sandbox, its hidden secrets
cannot be recovered by this repository. Retrieve them from the provider account
or rotate them and enter the new values directly in Railway. Never send a
Telegram token, API key, private key, or service-account JSON in chat.

## Why a deployment can appear to “expire after 24 hours”

A Railway deployment and an environment-variable value are separate things. A
short-lived environment commonly causes one of these symptoms:

1. **The process is still running but state disappeared:** no persistent volume
   was attached. Mount `/data` and set `AI_OS_DATA_DIR=/data`.
2. **The bot stopped replying:** the service is crash-looping or the public
   domain/webhook changed. Check Railway deployment logs and `GET /health`.
3. **Only one provider stopped working:** the provider token, IAM permission,
   Google share, or quota expired. Run the connector checks; do not blindly
   recreate the whole deployment.
4. **Telegram returns a conflict:** an old polling process is still using the
   bot. Stop the old process; production uses webhook mode only.

An approval code or provider token that really expired must be regenerated at
that provider. Moving the code to Railway does not extend an external token's
lifetime.

## Deployment steps

### 1. Create the Railway service

1. Create or open the Railway project and add a service from the GitHub
   repository.
2. Select the branch to deploy. The service should use the repository
   `Dockerfile`; do not add a custom start command unless it is exactly:

   ```text
   python3 -u -m connectors.telegram_webhook_runtime_memory
   ```

3. Generate a public Railway domain. Railway supplies `PORT`; do not hard-code
   a port in the variables. Set `TELEGRAM_WEBHOOK_BASE_URL` only when using a
   stable custom HTTPS domain. Otherwise the code uses
   `RAILWAY_PUBLIC_DOMAIN`.
4. Add a Railway Volume to this service with mount path **`/data`**.
5. Add `AI_OS_DATA_DIR=/data`.

The volume is essential. Without it a redeploy can reset proactive settings,
standing orders, open loops, the calendar reminder ledger, the scheduler
idempotency ledger, and project snapshots.

### 2. Add the minimum variables

Set these in the Railway **service** (not only at the project level if the
service does not inherit them):

| Variable | Required | Value |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | yes | Current token from BotFather; secret |
| `TELEGRAM_ALLOWED_CHAT_ID` | strongly recommended | Your private Telegram chat ID |
| `TELEGRAM_WEBHOOK_SECRET` | recommended | A new random HTTPS-safe secret; keep it stable across restarts |
| `AI_OS_DATA_DIR` | yes | `/data` |
| `MANAGER_TIMEZONE` | recommended | `Asia/Riyadh` |
| `AWS_BEARER_TOKEN_BEDROCK` | for Bedrock | Bedrock bearer token; secret |
| `AWS_REGION` | for Bedrock | `us-east-1` (or the region where the model is enabled) |
| `BEDROCK_MODEL_ID` | for Bedrock | `us.anthropic.claude-sonnet-4-6`, or an enabled model ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | for direct Google access | Complete service-account JSON, preferably pasted as one value or base64; secret |
| `GOOGLE_SHEET_ID` | for Sheets | ID between `/d/` and `/edit` in the Sheet URL |
| `GOOGLE_CALENDAR_ID` | for Calendar actions | Real Calendar ID from **Integrate calendar**; do not use `primary` with a service account |

The webhook secret is derived from the Telegram token when omitted, but an
explicit secret avoids changing the webhook secret if the token is rotated.

### 3. Add the Google asset IDs you actually use

Use the same service account unless you intentionally create a separate one:

```text
GOOGLE_DRIVE_FOLDER_ID       # Drive folder for reports/new Docs
GOOGLE_DOCS_DOCUMENT_ID      # default letter/report document
GOOGLE_CALENDAR_ID            # writable Calendar ID
GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON  # optional; otherwise the general JSON is reused
```

Share each target Sheet, Drive folder, Doc, and Calendar with the
`client_email` inside `GOOGLE_SERVICE_ACCOUNT_JSON`. Calendar permission must be
**Make changes to events**. Enable the corresponding Google Sheets, Drive, Docs,
and Calendar APIs in the Google Cloud project.

The Apps Script Sheets gateway is an alternative/fallback path, not a second
credential:

```text
GOOGLE_SHEETS_WEBHOOK_URL
GOOGLE_SHEETS_WEBHOOK_SECRET
```

If these two are used, the matching `AGENT_SECRET` and `SPREADSHEET_ID` must be
set in the Apps Script project as well.

### 4. Add voice transcription variables only if voice messages are needed

The Bedrock bearer token does **not** authorize S3 or Amazon Transcribe. Use a
least-privilege AWS access-key pair for the audio path:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_S3_AUDIO_BUCKET
AWS_TRANSCRIBE_LANGUAGE_CODE=ar-SA
AWS_TRANSCRIBE_POLL_SECONDS=2
AWS_TRANSCRIBE_TIMEOUT_SECONDS=120
```

The required IAM permissions are limited to the Telegram-audio S3 prefix and
`transcribe:StartTranscriptionJob`, `GetTranscriptionJob`, and
`DeleteTranscriptionJob`. The runtime deletes the temporary S3 object and job
in a `finally` block.

## Optional connector variables

Add only the integrations you have configured. An unset optional connector
stays disabled or uses its documented no-key fallback.

### Model providers

```text
OPENROUTER_API_KEY                 # non-clinical model route; secret
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL_PROVIDER=auto             # auto, openrouter, or bedrock
AI_CLINICAL_PROVIDER=bedrock
OPENROUTER_FALLBACK_BEDROCK=1
OPENROUTER_REQUIRE_ZDR=0           # set 1 only when the OpenRouter account supports it
AI_MANAGER_MODEL=anthropic/claude-sonnet-4.6
AI_CRITIC_MODEL=openai/gpt-5.6-sol
AI_GOOGLE_MODEL=google/gemini-3.7-flash
```

Keep Bedrock configured for the clinical/private route. Do not send clinical
content to a provider unless its privacy policy and the application's routing
policy allow it.

### Project memory and scheduling

The three project-memory document IDs have safe defaults in code, but set these
if the new deployment uses different Docs:

```text
PROJECT_MEMORY_STATUS_DOC_ID
PROJECT_MEMORY_PROGRESS_DOC_ID
PROJECT_MEMORY_DECISION_DOC_ID
PROJECT_MEMORY_APPROVAL_TTL_SECONDS=900

PROACTIVE_ENABLED=1
PROACTIVE_WORKER_ENABLED=1
PROACTIVE_WORKER_INTERVAL_SECONDS=900
PROACTIVE_WORKER_DISPATCH_SCHEDULER=1
PROACTIVE_TELEGRAM_PUSH=1
```

Keep `AI_OS_DATA_DIR=/data`; changing only the volume without this variable
still writes state to the ephemeral container filesystem.

### GitHub, search, audio digest, and social content

```text
GITHUB_TOKEN                         # secret; read-only connector needs repo access
AI_OS_GITHUB_REPO=addn2030-svg/personal-ai-agent
YOUTUBE_API_KEY                      # optional; DuckDuckGo fallback exists
ELEVENLABS_API_KEY                   # optional audio-digest narration; secret
ELEVENLABS_VOICE_ID                  # optional
BUFFER_API_KEY                       # Buffer connector name; secret
BUFFER_DEFAULT_MODE=draft
CONTENT_DEFAULT_PLATFORM=linkedin
CONTENT_SHEET_ID
CONTENT_QUEUE_TAB=PUBLISH_QUEUE
GEMINI_API_KEY                       # optional content image/video; secret
CONTENT_MEDIA_FOLDER_ID              # Drive folder for generated media
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
GEMINI_VIDEO_MODEL=gemini-omni-1.1-flash
```

Use `BUFFER_API_KEY`, not `BUFFER_ACCESS_TOKEN`; the connector reads the former.
All Buffer output remains behind the approval flow.

### Finance, bridge, and commerce

```text
FINANCE_SHEET_ID
FINANCE_SHEET_GID
FINANCE_SHEET_RANGE
FINANCE_HUB_ENABLED=1
BRIDGE_API_KEY                       # enables the authenticated POST /chat bridge
BRAVE_SEARCH_API_KEY                 # optional commerce search
COMMERCE_CHECKOUT_WEBHOOK_URL
COMMERCE_CHECKOUT_SECRET             # or COMMERCE_SHARED_SECRET
COMMERCE_DELIVERY_ADDRESS
COMMERCE_DELIVERY_PHONE
COMMERCE_PAYMENT_PROFILE
```

Keep financial autopay disabled until you have deliberately tested the payment
provider and approval policy:

```text
MONEY_AUTOPAY_ENABLED=0
```

Do not place delivery addresses, phone numbers, payment credentials, or patient
identifiers in Git or in a variable used for diagnostics.

## Safe variable transfer

### Railway CLI

The Railway CLI supports listing variables and setting one variable from stdin.
That avoids putting a secret in shell history or command-line arguments.

1. Authenticate and link the CLI to the **target** project/service.
2. Set scalar values without printing them:

   ```bash
   printf '%s' "$TELEGRAM_BOT_TOKEN" \
     | railway variable set TELEGRAM_BOT_TOKEN --stdin --skip-deploys
   printf '%s' "$GOOGLE_SERVICE_ACCOUNT_JSON" \
     | railway variable set GOOGLE_SERVICE_ACCOUNT_JSON --stdin --skip-deploys
   ```

3. Set non-secret values normally, for example:

   ```bash
   railway variable set \
     AI_OS_DATA_DIR=/data \
     MANAGER_TIMEZONE=Asia/Riyadh \
     AWS_REGION=us-east-1 \
     BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6 \
     --skip-deploys
   ```

4. Redeploy once after the complete set is present. `--skip-deploys` prevents a
   half-configured deployment after every individual variable.

If the source is another Railway service, export its variables only to a
permission-restricted local file, link the target service, and set them there.
Delete the export after verifying the target. If the source is a 24-hour
sandbox, use the provider dashboards to regenerate missing values instead of
expecting the sandbox filesystem to survive.

### Railway dashboard

Open **Project → Service → Variables** and add the same names. Paste the full
Google service-account JSON as one value; do not add line-by-line key/value
fields from inside the JSON. Railway redeploys after variable changes unless
changes are saved in a single batch.

## Provider-side transfer checklist

- **Telegram:** stop any old polling process; after Railway starts, check
  `getWebhookInfo` or send `/time` to the bot.
- **Google:** share every asset with the new/current service-account email and
  confirm API enablement.
- **AWS:** use separate least-privilege permissions for Bedrock and
  S3/Transcribe where possible; verify the model is enabled in the selected
  region.
- **GitHub:** use a fresh least-privilege token if the previous one was ever
  pasted into a chat or committed.
- **Buffer/ElevenLabs/OpenRouter/etc.:** revoke an exposed key and create a new
  one; changing the Railway variable alone does not revoke the old key.

## Verification after deploy

Replace `<railway-domain>` with the generated Railway HTTPS domain:

```bash
curl -fsS https://<railway-domain>/health
curl -i https://<railway-domain>/ready
```

Expected `/health` is HTTP 200 even when an external provider is degraded.
`/ready` may be non-200 until Google Sheets credentials, permissions, and
required tabs are correct.

Then use Telegram:

```text
/time
/selftest
/ai_status
/storage_status
/proactive
/memory_status
```

For a local diagnostic run with the same non-secret configuration and secrets
kept in your local environment:

```bash
python3 -m connectors.connection_setup
python3 -m connectors.connection_setup --live
```

Finally redeploy once more and confirm that `/proactive` has no persistence
warning and that `/memory_status`/scheduler state remains. A deployment that
survives a restart but loses `data/state.json` is not fully migrated.

## Repository references

- `docs/railway-agent-runtime.md` — production entrypoint, volume, Bedrock,
  Sheets, Calendar, and voice details.
- `docs/connection-guide.md` — provider-by-provider setup and live probes.
- `docs/runtime-time-memory.md` — `/health`, `/time`, persistence, and post-deploy
  acceptance checks.
- `tests/test_production_entrypoint.py` — guards the module invocation that
  prevents Railway crash loops.

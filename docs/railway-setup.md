# Railway setup — step by step (new project, Infrastructure as Code)

This is the walkthrough for deploying Abdulrahman AI OS to a **brand-new Railway
project** using `.railway/railway.ts`.

- Migrating an existing deployment, or moving variables between hosts?
  See [`docs/railway-migration.md`](railway-migration.md).
- Full variable inventory and provider permissions?
  See [`docs/railway-agent-runtime.md`](railway-agent-runtime.md) and
  [`docs/connection-guide.md`](connection-guide.md).

---

## Read this before you start

### 1. `railway.json` / `railway.toml` no longer works for new services

Railway's old **Config as Code** is deprecated. New services **cannot** opt into
it, and existing files stop being read on **2026-12-01**. The replacement is
**Infrastructure as Code**: `.railway/railway.ts`, which is already in this
repository. Unlike the old format it also declares the **volume** and the
**variables**, so this file is the whole deployment, not just build settings.

Any older guide telling you to add a `railway.json` is out of date. Don't.

### 2. The free plan will not run this bot

| Plan | Credit | RAM/service | Volume | Reality for this bot |
|---|---|---|---|---|
| Trial (new accounts, 30 days) | $5 one-time | up to 1 GB | 0.5 GB | Runs fine — this is your on-ramp |
| Free (after trial) | $1/month | 0.5 GB | 0.5 GB | **Will not last a month** |
| Hobby | $5/month incl. $5 usage | up to 48 GB | 5 GB | The realistic floor for 24/7 |

Railway prices RAM at roughly **$10 per GB-month**. A 0.5 GB container running
24/7 is about **$5/month of compute before CPU, storage and egress**. The Free
plan's $1 credit covers roughly a fifth of a month.

So: start on the Trial, and know that **around day 30 you must either add $5/month
or move the bot**. Put a reminder in your calendar now — the failure mode is the
bot going quiet, not an error message.

If you would rather not pay: `render.yaml` in this repository still works, and
[`docs/free-hosting-migration.md`](free-hosting-migration.md) compares Render's
free plan (sleeps after 15 min, no persistent disk, state must live in Supabase)
against the paid options honestly.

### 3. What Railway cannot do for you

Setting a variable does **not** grant access. You still have to share each Google
Sheet, Drive folder, Doc and Calendar with the service-account email, and enable
the matching APIs in Google Cloud. A perfect Railway config with an unshared
Calendar is a bot that fails at the first reminder.

---

## Step 1 — Install the tools

```bash
# Railway CLI (the IaC engine lives in the CLI, and must be ≥ 5.42.1)
npm install -g @railway/cli
railway --version

# The SDK that .railway/railway.ts imports
cd /path/to/personal-ai-agent
npm install
```

Verify the config before it can touch your account. This runs offline, needs no
login, and checks the things that actually break this deploy:

```bash
npm run railway:check
```

Expected: `15 checks passed — .railway/railway.ts is safe to plan.`

## Step 2 — Create the account and project

```bash
railway login          # opens a browser
# railway login --browserless   # if you are on a headless machine
railway whoami
```

Then create the project and link this directory to it:

```bash
railway init -n abdulrahman-ai-os
railway link           # confirm project + environment (production)
railway status
```

Set your deploy region before the volume exists — a volume follows its service's
region, and moving it later means downtime. From the Railway dashboard:
**Account settings → preferred region → EU West (Amsterdam, `europe-west4`)** is
the closest option to Riyadh.

## Step 3 — Set the secrets (before the first apply)

`.railway/railway.ts` declares these as `preserve()`, meaning "keep whatever is
already in Railway". Set the real values now so the first apply has something to
preserve.

Use one command so Railway does not redeploy between each variable:

```bash
railway variables --skip-deploys \
  --set "TELEGRAM_BOT_TOKEN=..." \
  --set "TELEGRAM_ALLOWED_CHAT_ID=..." \
  --set "TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 24)" \
  --set "GEMINI_API_KEY=..." \
  --set "GOOGLE_SHEET_ID=..." \
  --set "GOOGLE_CALENDAR_ID=..."
```

> The correct syntax is `railway variables --set "KEY=value"` — plural
> `variables`, with a `--set` flag. `railway variable set KEY` does not exist.

The service-account JSON is multi-line, so paste it in the **dashboard** instead
(**Service → Variables → New Variable → raw editor**) as a single
`GOOGLE_SERVICE_ACCOUNT_JSON` value. Do not split the JSON into separate keys.

Where each value comes from:

| Variable | Source |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather → your bot → API token |
| `TELEGRAM_ALLOWED_CHAT_ID` | Your private chat ID. Without it, anyone who finds the bot can talk to it |
| `TELEGRAM_WEBHOOK_SECRET` | Generate a random one. It is derived from the token if unset, which means rotating the token silently changes the webhook secret |
| `GEMINI_API_KEY` | Google AI Studio |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud → IAM → Service Accounts → Keys → JSON |
| `GOOGLE_SHEET_ID` | The ID between `/d/` and `/edit` in the workbook URL |
| `GOOGLE_CALENDAR_ID` | Calendar Settings → **Integrate calendar**. Never `primary` with a service account |

**Never paste any of these into chat, a commit, or a GitHub issue.**

## Step 4 — Plan, read the plan, then apply

```bash
railway config plan
```

`plan` is read-only. It prints exactly what would change, with variable values
redacted as `«hidden»`. Expect roughly:

```
Plan: 2 to add, 0 to change, 0 to destroy
  + Create service ai-os
  + Create volume ai-os-data
```

**Read every line before applying.** Omitting a resource from
`.railway/railway.ts` means *deleting* it; destructive changes are marked, and
that marking is the only thing between you and a deleted volume.

```bash
railway config apply
```

## Step 5 — Generate the domain, then redeploy

This step has a trap that silently breaks the bot.

`connectors/telegram_webhook.py` resolves its public URL from
`TELEGRAM_WEBHOOK_BASE_URL`, falling back to Railway's built-in
`RAILWAY_PUBLIC_DOMAIN`. That built-in only reaches your **container** after a
domain exists *and* the service has been redeployed. On the very first deploy
there is no domain, so the container boots with an empty value, fails to register
the webhook, and reports it as a **permanent** config error — it does not
keep polling for it.

So the order matters:

```bash
railway domain          # generates <something>.up.railway.app
railway redeploy        # REQUIRED — the running container must pick up the domain
```

Only if you attach a **custom** HTTPS domain do you also set
`TELEGRAM_WEBHOOK_BASE_URL=https://your-domain.com` explicitly.

## Step 6 — Verify

```bash
curl -fsS https://<your-domain>.up.railway.app/health
```

`/health` must return **200**, and the JSON must show:

```json
{"ok": true, "telegram_mode": "webhook", "telegram_webhook": {"configured": true}}
```

If `"configured": false`, the webhook did not register — re-read Step 5.

```bash
curl -i https://<your-domain>.up.railway.app/ready
```

`/ready` may return **503** until Google Sheets credentials, sharing and tabs are
all correct. That is expected and is *not* a deploy failure — which is exactly
why the healthcheck in `.railway/railway.ts` points at `/health` and never at
`/ready`.

Then, from Telegram:

```text
/time            → confirms the bot is reachable and the timezone is right
/selftest        → per-connector status
/ai_status       → model routing
/storage_status  → where state.json lives
/proactive       → must show NO persistence warning
/memory_status
```

## Step 7 — Prove the state actually survives

This is the step people skip, and it is the one that matters. A deploy that
survives a restart but loses `data/state.json` is not finished.

```bash
railway redeploy
```

Then run `/proactive` and `/memory_status` again. Your settings, standing orders
and open loops must still be there. If they reset, the volume is not doing its
job — check that the mount path is `/data` **and** that `AI_OS_DATA_DIR=/data`.
Mounting the volume without the variable still writes to the ephemeral layer.

Note: a service with a volume takes **a few seconds of downtime on every
redeploy**, even with a healthcheck configured. Railway refuses to run two
deployments mounting the same volume, to avoid corruption. This is normal.

---

## Design decisions in `.railway/railway.ts`

Each of these is enforced by `npm run railway:check`, so a future edit cannot
quietly undo one.

| Setting | Value | Why |
|---|---|---|
| `startCommand` | `python3 -u -m connectors...` | The script form puts `/app/connectors` on `sys.path` instead of `/app`, raising `ModuleNotFoundError: No module named 'connectors'` and crash-looping forever |
| `healthcheckPath` | `/health` | `/ready` returns 503 until Sheets is configured; using it fails the first deploy permanently |
| `numReplicas` | `1` | Railway forbids replicas on a service with a volume, and a second replica would double-send every proactive brief |
| `sleepApplication` | `false` | A sleeping container wakes for an inbound webhook but **not** for the background proactive loop — the morning brief would silently stop |
| `builder` | `DOCKERFILE` | Pins the build to the repository Dockerfile instead of Railpack auto-detection |
| volume `sizeMB` | omitted | Inherits the plan default (0.5 GB Free/Trial, 5 GB Hobby). Railway can grow a volume but never shrink it |
| volume `region` | omitted | A volume always follows its service's region; pinning it can only create a mismatch that forces a downtime-causing migration |
| secrets | `preserve()` | The file is committed to Git. `preserve()` keeps the value that lives in Railway |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Deploy crash-loops, `ModuleNotFoundError: No module named 'connectors'` | Start command overridden to the script form | Restore the `python3 -m` form |
| Deploy never goes healthy | Healthcheck pointed at `/ready` | Point it at `/health` |
| `/health` 200 but bot never replies | `telegram_webhook.configured` is `false` | Generate the domain, then **redeploy** (Step 5) |
| Telegram returns a conflict error | An old polling process still holds the bot | Stop it; production is webhook-only |
| Settings reset after every deploy | Volume missing, or `AI_OS_DATA_DIR` not `/data` | Both are required, not either |
| Bot went quiet around day 30 | Trial credit ran out | Upgrade to Hobby, or migrate |
| `railway config plan` refuses to run | The service is still managed by a legacy `railway.json`/`railway.toml` | Remove that file; a service cannot use both systems |
| Volume permission errors | Image running as non-root UID | Set `RAILWAY_RUN_UID=0` (not needed here — `python:3.12-slim` runs as root) |

## Optional — apply from CI

Railway's [`railwayapp/config`](https://github.com/railwayapp/config) action plans
on pull requests and applies the reviewed plan on merge. It needs a **project
token** (scoped to one environment) stored as the `RAILWAY_TOKEN` repository
secret. The recipe is in Railway's Infrastructure as Code docs. Worth adding only
once the deployment is stable — until then, `railway config apply` from your
machine gives you the plan in front of you.

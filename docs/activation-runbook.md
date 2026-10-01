# First activation — Telegram bot + Railway + Supabase

Verified runbook for the first live activation. Every command here was checked
against the actual code, not against a template.

Run the automated verifier at any point:

```bash
python3 scripts/verify_activation.py                 # offline
python3 scripts/verify_activation.py --live          # + Supabase / Telegram probes
python3 scripts/verify_activation.py --live --url https://<app>.up.railway.app
```

It never prints secret values. Exit code 0 means every executed check passed.

---

## ⚠️ Five corrections to the activation spec

These were found by checking the code. Following the original spec would have
produced a bot that looks deployed and silently does nothing.

### 1. The webhook rejects any registration made without `secret_token`

This is the one that costs a day of debugging.

`connectors/telegram_webhook.py` authenticates every inbound update:

```python
supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
if not supplied or not hmac.compare_digest(supplied, WEBHOOK_SECRET):
    self._send_json(403, {"ok": False})
    return
```

So this command from the spec **breaks the bot**:

```bash
# ❌ DO NOT RUN — registers a webhook with no secret_token.
# Telegram then delivers updates the server answers with 403, forever.
curl -F "url=https://<RAILWAY_URL>/telegram/webhook" \
     https://api.telegram.org/bot<TOKEN>/setWebhook
```

**You almost never need to register manually.** The service registers itself on
every boot, with the secret, the right `allowed_updates`, and `max_connections`:

```python
bot.api("setWebhook", {
    "url": webhook_url,
    "secret_token": WEBHOOK_SECRET,
    "allowed_updates": json.dumps(["message", "callback_query"]),
    "drop_pending_updates": "false",
    "max_connections": "10",
})
```

If you must register by hand, include the secret:

```bash
curl -sS -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  --data-urlencode "url=https://<RAILWAY_URL>/telegram/webhook" \
  --data-urlencode "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
  --data-urlencode 'allowed_updates=["message","callback_query"]' \
  --data-urlencode "max_connections=10"
```

If `TELEGRAM_WEBHOOK_SECRET` is **not** set, the server derives it from the bot
token, and your manual call must use the identical value:

```bash
# the exact derivation used by _ensure_webhook_secret()
python3 -c 'import hashlib,os;print(hashlib.sha256((os.environ["TELEGRAM_BOT_TOKEN"]+":webhook").encode()).hexdigest()[:48])'
```

Set `TELEGRAM_WEBHOOK_SECRET` explicitly instead. Otherwise rotating the bot
token silently changes the webhook secret and the bot goes mute.

### 2. There is no ASGI app — `uvicorn` would fail at import

The spec suggested `uvicorn connectors.telegram_webhook:app --host 0.0.0.0 --port $PORT`.

There is no `app` object. This service is a standard-library
`ThreadingHTTPServer`, and `uvicorn`/`fastapi`/`flask` are not in
`requirements.txt`. The only correct start command — already the Dockerfile
`CMD` — is:

```text
python3 -u -m connectors.telegram_webhook_runtime_memory
```

The `-m` form is mandatory. Running it as a script puts `/app/connectors` on
`sys.path` instead of `/app`, so `from connectors import ...` raises
`ModuleNotFoundError` and the deploy crash-loops. Guarded by
`tests/test_production_entrypoint.py`.

### 3. The chat allow-list variable is `TELEGRAM_ALLOWED_CHAT_ID`

The spec called it `ALLOWED_CHAT_ID`. The code reads only the prefixed name
(`connectors/telegram_bot_legacy.py:21`). A variable named plain
`ALLOWED_CHAT_ID` is ignored — which means **the bot answers everyone**, with no
error to tell you.

### 4. The Supabase tables are not the ones listed

| Spec said | Reality |
|---|---|
| `public.state_snapshots` | ✅ exists — `supabase/01_state_snapshots.sql` |
| `public.tasks` | ❌ the table is **`public.tasks_mirror`** |
| `public.agent_intake` | ❌ not defined anywhere in this repository |

`tasks_mirror` is named that deliberately. It is a **one-way, rebuildable
mirror** of the `tasks` section of `state.json`; the state file remains the only
source of truth. Renaming it to `tasks` would invite writing to it directly,
which is exactly the "double booking" failure the design avoids. The name is
configurable via `SUPABASE_TASKS_TABLE` if you really need it.

`agent_intake` has no migration, no reader and no writer. Tell me what it should
hold and I will write the migration; until then, treat its absence as correct.

### 5. Blanket-ignoring `data/` would orphan a tracked file

The spec asked for `data/` in `.gitignore`. Don't add it: `data/master-sheet.xlsx`
is tracked and needed. The repository already ignores the runtime state
per-file (`data/state.json`, `data/audit.jsonl`, `data/backups/`,
`data/memory/`), which is the correct, narrower rule.

---

## What was fixed in this pass

**`credentials.json` was not ignored.** The pattern `*.credentials.json` does
not match a bare `credentials.json` — which is precisely the filename Google
Cloud gives you when you download an OAuth client. Confirmed with git:

```console
$ git check-ignore -q credentials.json && echo IGNORED || echo "NOT IGNORED"
NOT IGNORED        # before
IGNORED            # after
```

`.gitignore` now also covers `token.json`, `client_secret*.json` and
`service-account*.json`. No tracked file was orphaned by the change.

---

## Step 1 — Git hygiene

```bash
python3 scripts/verify_activation.py
```

Expect `PASS` on every `.gitignore` check and on
"no .env / credentials.json / secrets/ tracked in Git".

## Step 2 — Runtime contract

Already verified by the script, and confirmed by booting the real service:

| Requirement | Status |
|---|---|
| `PORT` from env, default 8080 | ✅ `telegram_webhook.py:53` |
| `TELEGRAM_BOT_TOKEN` from env | ✅ `telegram_bot_legacy.py` |
| chat allow-list from env | ✅ as `TELEGRAM_ALLOWED_CHAT_ID` |
| binds `0.0.0.0:$PORT` | ✅ `ThreadingHTTPServer(("0.0.0.0", PORT))` |
| `/health` returns 200 | ✅ measured, returns 200 even when degraded |

## Step 3 — Supabase handshake

The project `https://hngdqjdzhusgwxespyru.supabase.co` is **live and awake** —
it answers API requests with a proper GoTrue error when no key is supplied.

Create the tables (SQL Editor → run each file):

1. `supabase/01_state_snapshots.sql` → `public.state_snapshots`
2. `supabase/02_tasks_mirror.sql` → `public.tasks_mirror`

Then verify with a key present:

```bash
export SUPABASE_URL="https://hngdqjdzhusgwxespyru.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="sb_secret_..."     # server-side only
python3 scripts/verify_activation.py --live
```

The verifier distinguishes a **missing table** (PostgREST `PGRST205`) from
**RLS blocking the read** (HTTP 401/403) — the two look identical in a plain
`curl` and are completely different problems.

> Reading with the anon/publishable key returning nothing is **correct**: both
> tables have RLS on with no policies, so the public key cannot read a row.
> Writes additionally require `SUPABASE_WRITE_ENABLED=1`.

## Step 4 — Railway configuration

Covered by [`docs/railway-setup.md`](railway-setup.md). The container contract:

| Setting | Value |
|---|---|
| Start command | `python3 -u -m connectors.telegram_webhook_runtime_memory` |
| Port | `$PORT`, injected by Railway (code defaults to 8080) |
| Healthcheck | `/health` — never `/ready` (503 until Sheets is configured) |
| Volume | mounted at `/data` **and** `AI_OS_DATA_DIR=/data` |
| Replicas | 1 (volumes forbid replicas) |

Both halves of the volume requirement are enforced by
`npm run railway:check`.

## Step 5 — Webhook registration

Order matters:

```bash
railway domain      # generate the public domain
railway redeploy    # REQUIRED: the running container must receive RAILWAY_PUBLIC_DOMAIN
```

The service then registers its own webhook, with the secret. Confirm:

```bash
curl -sS "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo" | python3 -m json.tool
```

Read these fields:

| Field | Expected | If wrong |
|---|---|---|
| `url` | `https://<app>.up.railway.app/telegram/webhook` | empty → the container never got the domain; redeploy |
| `pending_update_count` | `0` | growing → the server is rejecting deliveries |
| `last_error_message` | absent | `Wrong response from the webhook: 403 Forbidden` → registered without `secret_token` |

## Step 6 — Acceptance test

```bash
curl -sS https://<app>.up.railway.app/health | python3 -m json.tool
```

Required:

```json
{"ok": true, "telegram_mode": "webhook", "telegram_webhook": {"configured": true}}
```

`"configured": false` means the webhook never registered — re-read Step 5.

Then from the authorised Telegram chat:

| Command | Confirms |
|---|---|
| `/start` | the bot replies and records the owner chat id |
| `/diag` | per-channel diagnostics, including Supabase |
| `/time` | timezone is `Asia/Riyadh` |
| `/storage_status` | state is at `/data/state.json`, not the ephemeral layer |
| `/proactive` | **no persistence warning** |
| `/backup_now` | pushes a snapshot — then `/backups` lists it |

Finally, prove persistence actually works — the step that is usually skipped:

```bash
railway redeploy
```

Re-run `/proactive` and `/memory_status`. If the settings survived, the volume
is doing its job. If they reset, `AI_OS_DATA_DIR` is not `/data` — mounting the
volume alone is not enough.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot silent, `/health` is 200 | Webhook registered without `secret_token` → every update 403s | Re-register with `secret_token`, or just redeploy and let the service do it |
| `getWebhookInfo.url` empty | Container never received `RAILWAY_PUBLIC_DOMAIN` | `railway domain` then `railway redeploy` |
| Bot answers strangers | Variable named `ALLOWED_CHAT_ID` instead of `TELEGRAM_ALLOWED_CHAT_ID` | Rename it |
| `ModuleNotFoundError: No module named 'connectors'` | Start command uses the script form | Use `python3 -u -m …` |
| Deploy never healthy | Healthcheck points at `/ready` | Point it at `/health` |
| Settings reset every deploy | Volume mounted but `AI_OS_DATA_DIR` unset | Set `AI_OS_DATA_DIR=/data` |
| Supabase table reads return `[]` with anon key | RLS on, no policies — by design | Use the secret key server-side |
| `PGRST205` in a Supabase probe | The table does not exist | Run the migration in `supabase/` |

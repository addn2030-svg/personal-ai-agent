# Hermes Agent — Test & Monitoring Kit

Everything needed to deploy **Hermes Agent** (Nous Research) on Railway, chat with it
from Telegram or WhatsApp, and watch it live through Supabase + a monitoring dashboard.

> This kit is **self-contained** under `hermes/` and does not touch the main AI OS
> (`engine/`, `connectors/`, `supabase/01_*.sql`, …). The Hermes Supabase tables live
> next to the existing `state_snapshots` / `tasks_mirror` tables without conflict.

---

## ⚠️ Critical security rule (read first)

**Never store API keys or `.env` values in a Sheet or in Supabase tables.**

- Sheet cells are readable even when hidden (formulas, named ranges, connectors).
- Supabase data leaks instantly if RLS is off or the anon key is public.
- The correct place for secrets = **Railway → service → Variables tab**. Railway
  injects them into the container at runtime.
- Supabase only stores **non-sensitive** data: run status, timestamps, token counts,
  error summaries (never raw prompts with personal data, never keys).

Also:
- Don't commit `.env` ( already excluded by the repo `.gitignore`).
- Don't expose `SUPABASE_SERVICE_ROLE_KEY` in client-side code — the dashboard uses
  only the anon/publishable key + read-only RLS policies.
- Don't run a heavy open-source model on Railway (RAM/CPU cost). Use OpenRouter's
  free tier, AWS Bedrock, or a local GPU exposed as an OpenAI-compatible endpoint.

---

## 📋 Master build sheet (track progress here)

Tick the boxes directly in this file as you go (`[ ]` → `[x]`).

| # | Task | Tool | Output | Status |
|---|------|------|--------|--------|
| 1 | Create Railway account + project | Railway | Empty project | [ ] |
| 2 | Deploy Hermes template (Telegram or WhatsApp) | Railway | Running container + `/data` volume | [ ] |
| 3 | Add secrets to Railway Variables tab | Railway | Env vars injected | [ ] |
| 4 | Create Supabase project + tables | Supabase | `agent_runs`, `agent_logs`, `agent_config` | [ ] |
| 5 | Connect Hermes → Supabase (Webhook or MCP) | Hermes | Logs flow into Supabase | [ ] |
| 6 | Deploy monitoring dashboard | Railway / any static host | Live dashboard URL | [ ] |
| 7 | Link WhatsApp (QR) or start Telegram | Phone | Bot responds | [ ] |
| 8 | Verify end-to-end | Phone + Dashboard | Message in → log appears | [ ] |

---

## What's in this kit

| Path | Purpose |
|------|---------|
| `railway.env.example` | Step 3 — every Railway variable, documented, with empty values |
| `supabase/01_hermes_monitoring.sql` | Step 4 — tables + RLS + read-only policies + helper view |
| `supabase/functions/log-run/index.ts` | Step 5, Option B — Edge Function webhook that writes runs/logs |
| `mcp-supabase.example.md` | Step 5, Option A — Supabase MCP server config for Hermes |
| `dashboard/index.html` | Step 6, Option C — zero-build monitoring dashboard (single file) |
| `dashboard/config.example.js` | Dashboard config template (anon key only — safe if RLS is on) |
| `scripts/verify_e2e.sh` | Step 8 — proves the whole Supabase pipeline before Hermes is wired |
| `scripts/log_run.py` | Zero-dependency CLI/library to insert runs & logs (cron, hooks, tests) |

---

## Step 1–2 — Railway project + Hermes template

1. Create an account at <https://railway.com> and an empty project.
2. Deploy the Hermes Agent template (search "Hermes Agent" in Railway templates, or
   deploy the official image `nousresearch/hermes-agent:latest` as a **worker** service).
3. Confirm a **volume is mounted at `/data`** — Hermes keeps its state, sessions and
   WhatsApp pairing there; without it every redeploy wipes the agent's memory.

## Step 3 — Railway Variables (put secrets HERE, nowhere else)

Open Railway → your Hermes service → **Variables**, and set the values listed in
[`railway.env.example`](railway.env.example). Summary:

**LLM backend (choose one):**
- **OpenRouter (recommended for reliability):** `OPENROUTER_API_KEY`
- **AWS Bedrock:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (e.g. `us-east-1`)
- **Free open-source endpoint:** `OPENAI_BASE_URL` (your Ollama/vLLM endpoint) +
  `OPENAI_API_KEY` (dummy value ok)

**Messaging (choose one or both):**
- **Telegram:** `TELEGRAM_BOT_TOKEN` (from @BotFather) + `TELEGRAM_ALLOWED_USERS`
- **WhatsApp:** `WHATSAPP_ENABLED=true`, `WHATSAPP_ALLOWED_USERS=9665XXXXXXXX` (no `+`)

**Supabase (server-side only):**
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` — server-side only, never in a client
- `HERMES_WEBHOOK_URL` + `HERMES_WEBHOOK_SECRET` — if using the Edge Function (Step 5B)

## Step 4 — Supabase tables

1. Create a project at <https://supabase.com> (free tier is fine — note: free projects
   pause after ~7 days of inactivity; the daily heartbeat row from Hermes keeps it awake).
2. Open **SQL Editor** → paste and run
   [`supabase/01_hermes_monitoring.sql`](supabase/01_hermes_monitoring.sql).
3. Verify in Table Editor: `agent_runs`, `agent_logs`, `agent_config` exist and
   **RLS is enabled** on all three.

## Step 5 — Connect Hermes → Supabase

**Option A — MCP (recommended, more flexible).** Add the Supabase MCP server to the
Hermes config so the agent itself can call tools that insert into `agent_runs` /
`agent_logs`. See [`mcp-supabase.example.md`](mcp-supabase.example.md).

**Option B — Webhook (simpler).** Deploy the Edge Function:

```bash
supabase functions deploy log-run --project-ref <YOUR_PROJECT_REF>
supabase secrets set HERMES_WEBHOOK_SECRET=<random-long-string>
```

Then point Hermes' post-run hook (or a wrapper script / `scripts/log_run.py`) at:
`https://<project-ref>.supabase.co/functions/v1/log-run` with header
`x-hermes-secret: <same secret>`.

## Step 6 — Monitoring dashboard

**Option C (shipped here, fastest):** `dashboard/index.html` — a single static file,
no build step, mobile-responsive. It shows success rate, average duration, token
trend, estimated cost and recent errors, auto-refreshing every 15 s.

```bash
cd hermes/dashboard
cp config.example.js config.js     # fill SUPABASE_URL + anon key
python3 -m http.server 8080        # or deploy as a static site on Railway
```

Without `config.js` it runs in **demo mode** with sample data so you can see the
layout before Supabase exists.

Alternatives: **Option A** Supabase Platform Kit embedded in a Next.js page;
**Option B** Grafana + Loki + Prometheus via the Railway Grafana template (best for
real-time alerts). Start with C; upgrade only if you need alerting.

## Step 7 — Link your phone

- **Telegram:** open your bot (the username @BotFather gave you) → `/start` → say "hello".
- **WhatsApp:** open the Hermes logs/dashboard, scan the QR code with
  WhatsApp → Linked Devices.

## Step 8 — Verification checklist

Before Hermes is even wired, prove the pipeline works:

```bash
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=<secret key>     # server-side shell only
export SUPABASE_ANON_KEY=<anon key>               # optional: verifies read policy
bash hermes/scripts/verify_e2e.sh
```

Then the real test:
- [ ] Send "hello" to the bot → reply arrives.
- [ ] A new row appears in `agent_runs` with `status = completed`.
- [ ] `agent_logs` shows the event.
- [ ] Dashboard reflects the run within seconds.

---

## 🚫 What NOT to do

- Don't paste `OPENROUTER_API_KEY`, `AWS_SECRET_ACCESS_KEY`, or bot tokens into a Sheet,
  a chat, or a Supabase table.
- Don't commit `.env` to GitHub.
- Don't expose `SUPABASE_SERVICE_ROLE_KEY` in client-side code.
- Don't run a heavy open-source model on Railway — run it on a local GPU or use
  OpenRouter's free tier.
- Don't leave the public read policies enabled if the logs could ever contain personal
  details — the SQL file includes a commented "lockdown" block to revoke them.

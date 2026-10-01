# Readiness Status — 16-Step Build Sheet

Source of record: Google Sheet *newAI personal smart agent*
(`1EUI20Kfe21h6osvSYyRdpiHTnbu3UbNLYicxweSPD60`).
Sheet header on 2026-10-01: **16 steps · 13 complete · 81.3% · "In Active Development"**.

This file reconciles each sheet row against what actually exists in this repository,
so "complete" means *verified in code*, not *marked TRUE in a cell*.

## Verified complete (13)

| Step | What it claims | Evidence in repo |
|---|---|---|
| ST-01 | Persona, role instructions, memory architecture | `prompts/`, `engine/memory.py`, `engine/store.py` |
| ST-02 | Model tier & token budget | `connectors/model_gateway.py`, `connectors/model_router.py` |
| ST-03 | `.env` / `.env.example`, zero hardcoded keys | `.env.example`, `.gitignore`, `engine/env_file.py` |
| ST-04 | Primary LLM key | `GEMINI_API_KEY` (+ `KIMI_API_KEY` overflow) read from env only |
| ST-05 | Google service account, Sheets/Drive scopes | `connectors/google_credentials.py`, `connectors/google_workspace.py` |
| ST-07 | Tool dispatch + schema validation | `engine/skill_registry.py`, `connectors/*` dispatch layer |
| ST-08 | Messaging webhook | `connectors/telegram_webhook.py`, `connectors/telegram_bot.py` |
| ST-09 | Confirmation gates for destructive actions | `engine/approve.py`, action queue |
| ST-10 | Token/cost circuit breaker | `tests/test_money_threshold.py`, 375 SAR threshold |
| ST-11 | Injection sanitization / output redaction | clinical minimization path, sanitizer logic |
| ST-12 | End-to-end dry run | `scripts/smoke_test.sh`, 669 unit tests (`python3 -m unittest discover -s tests`) |
| ST-13 | Retry with backoff | bounded retry + idempotent writes in connectors |
| ST-14 | Deployed service with healthcheck | `Dockerfile`, `render.yaml`, Railway persistent `/data` |

## Open (3)

| Step | Status | Remaining work |
|---|---|---|
| ST-06 — Web search provider | **Partially done, not keyed.** `connectors/web_search.py` exists and works key-free via DuckDuckGo, with optional `YOUTUBE_API_KEY`. | Set `TAVILY_API_KEY` or `SERPER_API_KEY` (now recognised by the connection doctor) for a reliable, rate-limit-free provider. `--guide search` prints the steps. |
| ST-15 — Supabase PostgREST client | **Code complete, deployment pending.** `connectors/supabase_client.py`, `supabase/01_state_snapshots.sql`, `supabase/02_tasks_mirror.sql`. | Run both SQL files in the project, then set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_WRITE_ENABLED=1`. Verify: `python3 -m connectors.supabase_client --live`. |
| ST-16 — Replace Sheet polling with PostgREST | **Blocked on ST-15.** `connectors/supabase_tasks.py` mirrors tasks one-way. | Advance the rollout stage (`python3 -m engine.rollout status|advance`) only on evidence; `kill` rolls back instantly. |

## Model routing — Bedrock vs. Claude vs. the rest

The gateway is explicit about who serves what (`connectors/model_gateway.py`):

- **Gemini** (`AI_MODEL_PROVIDER=gemini`, the default) — ordinary and clinical traffic.
- **Kimi / Moonshot** — automatic overflow when Gemini hits its daily quota.
- **AWS Bedrock (Claude)** — an explicit compatibility route, `BEDROCK_MODEL_ID`
  default `us.anthropic.claude-sonnet-4-6` in `AWS_REGION`.
- **OpenRouter** — legacy/compatibility only.

To make Bedrock the live route you need **both** credentials and intent:

```bash
# auth — either one
AWS_BEARER_TOKEN_BEDROCK=...          # Bedrock API key
# or
AWS_ACCESS_KEY_ID=... ; AWS_SECRET_ACCESS_KEY=...   # IAM: bedrock:InvokeModel, bedrock:Converse

AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
AI_MODEL_PROVIDER=bedrock             # only if Bedrock should serve ordinary traffic
```

Setting the keys alone does **not** divert traffic — Gemini stays the default until
`AI_MODEL_PROVIDER` is changed. That is deliberate: credentials are not a decision.

## Connection doctor — now covers the bot and both pending routes

```bash
python3 -m connectors.connection_setup            # config only, no network, no secrets printed
python3 -m connectors.connection_setup --live     # + one tiny live call per configured route
python3 -m connectors.connection_setup --json
python3 -m connectors.connection_setup --guide bedrock   # or: search, supabase, telegram, ...
```

From the phone the same table is `/connections` in the Telegram bot
(`engine/telegram_bot.py::diag_text`), so the new Bedrock and Web Search rows appear
there automatically.

Unconfigured **optional** routes (Kimi, Bedrock, Web Search, Supabase) report `○ optional`,
never `❌ missing` — an absent optional key is a valid state, not a failure. A half-configured
Bedrock (access key without secret) reports `⚠️ partial` and names the missing variable.

### Verification run in this sandbox (2026-10-01)

- `python3 -m unittest discover -s tests` → **669 tests, OK**.
- `python3 -m connectors.connection_setup` → 13 rows rendered; Bedrock and Web Search
  present and `optional` (no AWS keys in this environment).
- `connectors.model_gateway.probe_bedrock()` → `{'configured': False, ...}` — correct
  refusal, no credentials here; it will issue a real one-token Claude call once keys are set.
- `python3 -m connectors.web_search --check` → provider `ddg`, blocked by this sandbox's
  egress TLS policy. This is a network restriction here, not a code fault.

## Honest bottom line

12 of the 16 steps are complete *and* verified in code. ST-06 is code-complete but running
on the unkeyed fallback. ST-15/ST-16 are code-complete and test-covered but not yet pointed
at a live Supabase project, so the data layer is still Sheet-backed in production.
The real completion rate against *live, keyed* infrastructure is therefore closer to
**81% built / ~75% live**, and the remaining work is configuration, not engineering.

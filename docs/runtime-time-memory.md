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

### 1.1 The model clock (`engine/runtime_clock.py`)

The scheduler's timezone is not the same thing as the model knowing what day it
is. Nothing used to tell the model the current date, so the agent
answered "what day is today?" from training priors and named the wrong date.

`engine/runtime_clock.py` is now the single source of truth for "now". It reads
`MANAGER_TIMEZONE` (default `Asia/Riyadh`) and falls back to a fixed UTC+03:00
offset when the tz database is missing, so a slim container can never crash on
import. Two consumers:

- `runtime_time_context()` — injected as the **first** block of
  `engine/agent_runtime.build_context()`, so it survives context truncation and
  reaches the Gemini API path.
- `status_text()` — the `/time` Telegram reply (see §1.2).

The system prompt also instructs the model to refuse to guess a date when the
block is absent, instead of answering from training data.

### 1.2 `/time` — instant liveness and clock probe

`/time` (alias `/now`) answers straight from the process clock with **no model
call, no Google call, and no outbound network**. That makes it the one command
that cannot be broken by the thing you are diagnosing:

```text
🕒 وقت الخادم الآن: 2026-09-14 — الإثنين — 07:39
المنطقة الزمنية: Asia/Riyadh (UTC+03:00)
ISO: 2026-09-14T07:39:57+03:00
⏱️ مدة تشغيل العملية: 579 ثانية
🔁 آخر دورة استباقية مسجّلة: 2026-09-14 07:39:37+03:00
```

Triage when the agent goes quiet — run these in order:

| Result | Meaning | Next step |
| --- | --- | --- |
| `/time` answers | Process is alive and the webhook is serving | The fault is a provider: run `/ai_status` (Gemini), `/storage_status` (Sheets), `/selftest` |
| `/time` silent, uptime small on a later reply | Container is crash-looping | Open Railway → Deployments → Logs; check startup exceptions |
| `/time` silent, no reply at all | Webhook not reaching the app | `curl https://<host>/health`; check `RAILWAY_PUBLIC_DOMAIN`/`TELEGRAM_WEBHOOK_BASE_URL` and that Railway did not change the domain |
| `/health` 200 but Telegram silent | Telegram cannot deliver, or the secret mismatches | Re-run startup `setWebhook`; confirm `TELEGRAM_WEBHOOK_SECRET` |
| Scheduled jobs never fire but chat works | Proactive worker or scheduler dispatch off | Check the `🔁` heartbeat line above and `PROACTIVE_WORKER_ENABLED` |

`/health` is public and deliberately does **not** depend on Google, so Railway
never restarts a healthy process because an external API is degraded.

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

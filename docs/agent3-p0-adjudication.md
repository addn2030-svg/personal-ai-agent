# Agent 3 — P0 Architecture Adjudication

Date: 2026-08-24

## Decision

Adopt the **minimal P0 hardening** now. Defer Postgres, a durable job queue, full CI/staging, formal key-management infrastructure, and pgvector until real operating evidence justifies them.

## Weighted decision

| Criterion | Weight | Minimal P0 | Heavy P0 |
|---|---:|---:|---:|
| Fixes observed 409/timeout/404 failures | 30% | 9/10 | 10/10 |
| Implementation simplicity | 20% | 9/10 | 4/10 |
| New failure surface | 15% | 8/10 | 4/10 |
| Data-loss resilience | 15% | 6/10 | 10/10 |
| Privacy improvement now | 10% | 8/10 | 10/10 |
| Future scalability | 10% | 6/10 | 10/10 |
| **Weighted score** | **100%** | **8.0/10** | **7.8/10** |

The heavy architecture wins on ultimate resilience and scale, but the current evidence is a single-owner bot with low message volume and three concrete operational failures. The minimal architecture is therefore preferred for the next milestone because it removes the known failures with less operational complexity.

## P0 changes approved now

1. Telegram Webhook on Railway instead of `getUpdates` polling.
2. Webhook secret validation and bounded in-process update de-duplication.
3. Bounded Google Sheets retry: immediate + 1s + 2s + 4s.
4. Startup compatibility probe for required Sheets tabs and the deployed `upsert_metrics` action.
5. Separate `/health` liveness from `/ready` Google/Sheets readiness.
6. Clinical-private free text is minimized before generic Sheets or local Personal OS persistence.

## Explicitly deferred

- Postgres as System of Record.
- Durable external job queue/dead-letter queue.
- pgvector / Hybrid RAG.
- Full CI/CD pipeline and dedicated staging promotion workflow.
- Formal encryption-key service and full clinical access audit system.

## Upgrade triggers

Reconsider Postgres + durable queue when any of the following occurs:

- message volume reaches hundreds/day or multiple users are added;
- repeated data loss is observed despite bounded retry;
- concurrent processing/race conditions appear in real logs;
- a formal clinical/compliance requirement requires durable audit and encrypted source records;
- Sheets latency becomes a recurring operational bottleneck.

## Milestone acceptance criteria

- No Telegram HTTP 409 caused by bot polling after deployment.
- `/health` returns process liveness without depending on Google.
- `/ready` detects missing required tabs or an outdated Apps Script deployment.
- Transient Sheets writes are retried automatically.
- Duplicate webhook deliveries do not normally execute the same update twice within one running instance.
- Generic persistence does not store clear-text `CLINICAL_PRIVATE` content.

## Known limitation accepted for this milestone

Without a durable database/queue, an extreme process crash at the wrong moment can still lose post-acknowledgement work. This residual risk is accepted for the current single-user/low-volume phase and is the main trigger for a future Postgres + durable queue upgrade.

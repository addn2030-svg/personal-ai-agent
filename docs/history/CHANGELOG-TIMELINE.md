# Rehabilitation Chief-of-Staff Agent — Complete Historical Timeline

> **Scope:** every function, feature, capability, command, integration, fix and enhancement landed on `main` of
> `addn2030-svg/personal-ai-agent` from the first commit (**21 Aug 2026**) to the present (**15 Sep 2026**).
> **Sources:** git history of `main` (304 commits, 108 merged PRs), README release notes, `docs/v*.md`,
> `docs/SYSTEM_STATUS.md`, `docs/FINANCE_HUB.md`, `evaluation/*.md`.
> **Visual companion:** [`evolution-infographic.svg`](evolution-infographic.svg) / [`.png`](evolution-infographic.png)
> (regenerate with `python3 scripts/build_history_infographic.py`).

---

## At a glance

| Metric | Day 1 (21 Aug) | Today (15 Sep) |
|---|---|---|
| Engine modules (`engine/*.py`) | 13 | **64** |
| Connectors (`connectors/*`) | 0 | **57** |
| Test files / test functions | 0 / 0 | **44 / 373** |
| Prompt packs | 7 | **16** |
| Docs | 3 | **29** |
| Telegram commands | 0 | **60+** |
| Lines of Python (engine+connectors+tests) | ~3K | **~29K** |
| Commits / merged PRs | 14 | **304 / 108** |
| Elapsed | — | **26 days** |

**Versioning note.** The project carries several parallel version lines that appear in commit titles and README:
*AI OS* (v0.2 → v2.0, the core engine), *Production Telegram runtime* (Prod v0.5a → v0.9.6), *Rehab brief* (v1.3 / Phase 1.5),
*Mission orchestrator* (v0.7 → v0.9), *Direct Brief* (v2 → v2.1), *Super Manager* (v1 → v1.1), *Proactive* (v1.0 → v1.0.3),
*Money threshold* (v1.1), *Books context* (v2.0 → v3.0). They are listed below by **date**, with the line named in each entry.

---

## Phase 0 — Foundation (21 Aug 2026) · AI OS v0.2 → v0.4.1

**14 commits · engine 13 modules · 0 connectors**

### v0.2 — Architectural review fixes C1 + C2
- **Unified StateStore** (`engine/store.py`, `data/state.json`): single writer for all mutable data, atomic writes, version number with conflict rejection, rotating backups (last 5), `data/audit.jsonl` audit log. Google Sheet demoted to import/export format only.
- **Action queue + approval gate** (`engine/approve.py`, `engine/render_approvals.py`): follow-up drafts become `PENDING_APPROVAL` actions rendered to `reports/approvals-latest.html`; approval requires the **SHA-256 hash of the draft text** (`approve A-001 --hash …`), expires after 48 h, idempotent.
- **Waiting-for rot**: everything awaited (client reply, project movement) derived into `waiting_for`, surfaced in the brief; >14 days escalates to a decision issue.
- Brief & weekly-review engine (`engine/chief_of_staff.py`), pattern detection, daily inbox HTML (`tools/daily-inbox.html`).

### v0.3 — Manager Loop (adopted from external v4.1.1 review)
- `engine/manager.py`: two cycles — **fast every 15 min** (deterministic waiting-for sweep) and **full 06:00 Asia/Riyadh** (brief + dashboard) with catch-up and write-on-change.
- `waiting_for` schema v2: WAITING→OVERDUE state machine, one idempotent follow-up action per overdue item, follow-up draft prepared.
- `decision_requests`: formal decision requests (options + deadline) for stalled active projects; resolution logged with 30-day review; "convert to paused" actually executes.
- Change detection section "🔄 what changed since last brief" (new / status changed / closed).

### v0.3.1 — Voice Relationship Manager, Phase 1
- `engine/voice_call.py`: inbound-call transcript → caller & intent classification → structured summary → StateStore (contacts, callback tasks, waiting_for v2, leads, transfer requests) + follow-up draft to approval queue — **never sends**.
- Hard guards: no diagnosis from a call; caller speech = untrusted content (injection attempts rejected and logged as security events); data minimisation; idempotency by call ID.
- "📞 Calls" section in brief & dashboard; `voice_call.py demo A|B|C|D|E` and `ingest call.json`.

### v0.4 — Mandatory personal-teaching protocol
- `engine/learning_engine.py`: adaptive teaching plans → graded chunks with mandatory adaptive rulings (≥85 / 70–84 / 50–69 / <50) → per-concept mastery map (knowledge/reasoning/application + misconception flags) → spaced-repetition final assessment (1/3/7/14/30 days).
- Review lifecycle SCHEDULED→DUE→PRESENTED→ANSWERED→SCORED→COMPLETED; `learning_reviews` kept separate from the action queue.
- Morning brief: "📚 today's learning reviews (N min)" capped at two.
- `prompts/personal-training.md` live teaching protocol.

### v0.4.1 — ILPC methodology (Bob Pike Group)
- EAT / CPR / 90-20-8 design rules baked into the teaching prompt; `learning_engine.py outline LP-001` generates ILPC outlines.
- First complete material: `materials/lp-001-lean-six-sigma-ilpc.md`.

### Same-day infrastructure
- Sheet template (`engine/make_template.py`), bootstrap & smoke-test scripts, CI workflow moved to `docs/ci-workflow.yml`.
- Safe push script with automatic backup of previous content.
- **ChatGPT & VS Code bridge**: `engine/export_for_chat.py` + editor tasks + `docs/using-the-agent.md`.
- **24/7 autostart** for Windows / macOS / Linux (`autostart/`) + daily loop heartbeat + `docs/autostart.md`.
- **Google Drive bridge**: live sheet import (`engine/import_drive.py`), decision-speed plan, fix for public-request invalidation.
- **Sources & scientific learning bridge**: `--sources` mode + `knowledge_sources` section; import of 24 sources + 28 weak-point protocols; learning plans LP-002 / LP-003.

---

## Phase 1 — Chief-of-Staff Core & First Mobile Runtime (22 Aug 2026) · AI OS v0.5 → v0.9 · Telegram bot v1

**40 commits (busiest foundation day) · engine 13 → 51 · connectors 0 → 8 · prompts 7 → 13**

### Life-OS features
- **14 life doors** + "door of the day" in the brief + real income baseline.
- **Knowledge asset registry** (`engine/asset_registry.py`): unified back-tracking of books/docs/tabs/files/contracts, filter UI, auto-sync in the full cycle.
- 4 new playbooks: travel, negotiation, writing, family (`prompts/`).
- Agent skills inventory (11 skills + 9 engines) with routing table (`docs/agent-skills.md`); skills audit 19/19 (`evaluation/skills-audit-2026-08-22.md`).
- **Second skills wave**: OKR engine (`engine/okr.py`), Health Guardian energy log (`engine/energy_log.py`), real E-S-B-I finance, green Friday brief, voice capture from Telegram, `/okr` and energy commands.
- Social triage (`engine/social_triage.py`) and full-text search (`engine/search.py`).
- Fix: complaint pattern ("bad/complain") mis-classification + cleanup of wrongly classified draft.

### AI OS v0.5 core (`docs/v0.5-architecture.md`)
- Orchestrator, permissions, memory, RAG (`engine/orchestrator.py`, `permissions.py`, `memory.py`, `rag.py`), observability & telemetry, evaluation harness (`engine/evaluate.py`), mobile Control Center (`engine/control_center.py`), `v05_cycle.py`.
- **RCJY rehabilitation leadership training** for the Chief of Staff: `knowledge/rcjy-rehabilitation-work-context.md`, `rcjy-rehabilitation-service-packages.md`, `training/rcjy-chief-of-staff-scenarios.md` — morning routing prioritises hospital leadership & rehab operations; patient-identifiable data never enters general memory or GitHub.

### AI OS v0.6 — Self-improving Chief of Staff (`docs/v0.6-*.md`)
- Reflection engine, behaviour model, self-review, decision quality scoring (`engine/reflection_engine.py`, `behavior_model.py`, `self_review.py`, `decision_quality.py`, `v06_cycle.py`); `evaluation/self_improvement_cases.json`.

### AI OS v0.7 — Trust & change intelligence (`docs/v0.7-*.md`)
- `engine/change_intelligence.py`, `trust_dashboard.py`, `connector_health.py`, `backup_verify.py`, `v07_cycle.py`; `evaluation/test_v07_trust.py`.

### AI OS v0.8 — Live connectors (`docs/v0.8-live-connectors.md`)
- Live Gmail, Calendar, Drive, GitHub and Telegram connectors; unified source sync (`engine/live_sync.py`, `unified_inbox.py`, `v08_cycle.py`, `connectors/google_workspace.py`, `github_live.py`, `telegram_live.py`).

### AI OS v0.9 — Master profile & Drive knowledge governance
- `knowledge/master-professional-profile.yaml`, `drive-knowledge-map.md`, `drive-source-policy.yaml`, `engine/source_governance.py`, `docs/information-governance.md`.

### Telegram production bot v1 (PRs #1–#6 era, same day)
- `connectors/telegram_bot.py` secure polling bot: `/start /help /profile /sources /selftest`; owner-lock via `TELEGRAM_ALLOWED_CHAT_ID`; tests for command source & owner security; `docs/telegram-setup.md`.
- Deployment: `requirements.txt`, `Dockerfile` (Railway-ready), AWS Bedrock dependency.
- **Free-text answers with Claude on AWS Bedrock**; categorised intake and conversations persisted to Sheets; Railway volume memory & conversation state.
- Bounded memory + knowledge retrieval runtime (`engine/agent_runtime.py`).
- **Private AWS Transcribe voice pipeline** with cleanup (`connectors/aws_transcribe.py`); Telegram wired to memory, retrieval and voice transcription.
- Secure **Apps Script webhook** for Sheets (`connectors/google_sheets_webhook.gs`) with read-search & approved updates, no JSON key required; Sheets intelligence connector (`connectors/sheet_intelligence.py`).
- AI responses always grounded in verified professional profile (`evaluation/profile-grounding-cases.json`); executive operating tabs prioritised in context.
- Fix: repaired Telegram Sheets commands + Python syntax validation.
- `docs/railway-agent-runtime.md` least-privilege setup.

---

## Phase 2 — Clinical Layer & Durable Memory (24–25 Aug 2026)

### 24 Aug — Rehab brief v1.3 / Phase 1.5 (PRs #8–#11)
- **Executive brief discovery** (`connectors/brief_discovery.py`): `/brief` reads a bounded live Sheets snapshot, diffs against the last persisted snapshot, detects changes, incomplete items, upcoming dates, blockers, decisions; updates `Executive_Brief` tab. Snapshot stored under `AI_OS_DATA_DIR` (Railway volume `/data`).
- **Rehab supervisor form** (`connectors/rehab_supervisor_form.gs`): `createRehabSupervisorForm` + `testRehabIntegration`.
- **Phase 1.5 — safe pre-visit intelligence** (`engine/previsit_intelligence.py`, `prompts/previsit-intelligence.md`, `connectors/previsit_patient_form.gs`): case-code-only input (names/MRN/IDs/phones rejected), conservative safety screening first, labels URGENT / PRIORITY / ROUTINE_CLINICIAN_REVIEW, irritability estimate, interview gaps, differential hypotheses for clinician review only; approved pre-visit link workflow.
- Fixes: keep brief available before gateway upgrade; format brief for Telegram readability.
- **P0**: switch Telegram from polling to **webhook** (`connectors/telegram_webhook.py`); harden Sheets & privacy. Fix duplicated `/brief` and Sheets timeout path (#11).

### 25 Aug — Memory & Calendar
- Fix historical memory retrieval and verified save receipts.
- **Unified provenance-first context retrieval** (`engine/context_service.py`), semantic multi-source retrieval, durable provenance-aware memory; Arabic prefix handling and contract concept expansion.
- **Confirmed Google Calendar actions** (`connectors/calendar_actions.py`, `calendar_intent.py`): create/confirm events, reminder scheduler with Telegram alerts, Arabic dual-hour reminder phrasing, Railway service-account access, deployment/consent docs.

---

## Phase 3 — Multi-Model Production Team (27–28 Aug 2026) · Prod v0.5a → v0.9.6

**68 commits on 28 Aug — the single busiest day**

- **Prod v0.5a** (#14): OpenRouter primary with permanent Bedrock fallback (`connectors/model_gateway.py`, `.github/workflows/production-model-router.yml`).
- **Prod v0.6** (#15): multi-agent **task delegation** (`connectors/task_delegation.py`); `/delegate`, `/agents`, `/council`; routing & privacy-guard tests.
- **Prod v0.7** (#16) + hotfix v0.7.1 (#17): read-only Google knowledge gateway; robust service-account parsing.
- **Prod v0.8** (#18–#20) + hotfix v0.8.1: Apps Script knowledge gateway (Sheets + Drive), `/google_access` diagnostics.
- **Rollback** (#21): Google Knowledge removed, stable v0.6 workflow restored (8 targeted rollback commits).
- **AI Team Mission Orchestrator v0.7** (#22): shared missions for Claude, GPT, Gemini (`connectors/team_orchestrator.py`); specialists routed through direct APIs (#23); Gemini routing hotfix (#24); provider diagnostics helper + tests (`connectors/provider_diagnostics.py`, #26).
- **Mission v0.8** (#27): sequential Gemini→GPT handoff.
- **Mission v0.9** (#28): Bedrock-first lean token budgets (`connectors/bedrock_team.py`, `lean_missions.py`); v0.8 regression tests isolated; de-identified workflow guardrail; **v0.9.1** Bedrock diagnostics & tiny probe (#29); **v0.9.2** Nova Micro default lean model (#30); Arena research-capsule format documented (`research_capsules/README.md`).
- **v0.9.3 / 0.9.3a** (#31–#32): on-demand operational context capsules + source status (`connectors/ops_context.py`).
- **v0.9.4 / 0.9.4a** (#34–#36): hardened Google context transport, mounted credential files, runtime failure reasons (`connectors/google_credentials.py`).
- **v0.9.5** (#37): Calendar reminders stay active in webhook mode (reminder worker test).
- **v0.9.6** (#38–#39): natural-language Calendar requests routed to guarded actions; mobile-friendly confirmation (`connectors/mobile_calendar_confirm.py`).

---

## Phase 4 — Portfolio, Direct Brief & Safety Gates (29–31 Aug 2026)

### 29 Aug
- **Portfolio v1** (#40–#42): expert rehabilitation & healthcare-AI page (`portfolio/`), LinkedIn link, GitHub Pages, refresh from CV 2026 V3; later archived from the private repo.
- Fix Google Sheets writes with **direct-first** production route (#43); production import path fix (#44); direct Sheets diagnostics (#45).
- `/brief` made resilient with direct Sheets writes (#46), best-effort snapshot (#47), **Direct Brief v2** rebuilt as runtime command (#48), **v2.1 with Google Calendar** (#49) (`connectors/brief_runtime.py`).
- **Gate 0.5**: fail closed on ambiguous Calendar dates/times + regression tests.

### 30 Aug — State safety & WO-8
- **State Safety foundation** (#64): StateStore concurrency hardening, transactional Manager writes and persistent loop markers, CI coverage (`docs/state-safety-manager-foundation.md`, `tests/test_state_safety_manager.py`).
- Gate 0.5: fail closed on invalid Calendar references + edge cases (#63).
- **WO-8 linked multi-intent capture** (#65): conservative linked multi-intent recorder, multi-intent-aware unified inbox (`engine/multi_intent.py`, `connectors/multi_intent_runtime.py`).
- **Super Manager v1 → v1.1** (#66) grounded in WO-8 record links (`connectors/super_manager.py`); FAST manager compatible with WO-8 NEEDS_INPUT links.
- **FAST-only Manager canary** behind OFF-by-default flag, wired into webhook runtime (#67) (`connectors/manager_fast_canary.py`).

### 31 Aug — Truth & natural actions
- **Capability Truth** (#68): runtime capability truth + action preflight, privacy correction, blocks blanket "text-only" denials, shopping boundaries (`connectors/capability_truth.py`, `capability_runtime.py`); `/capabilities`.
- **Natural-language Action Executor** with approval receipts (#69) (`connectors/action_executor.py`, `action_runtime.py`): `/act`, `/action_status`, `/approve_action`, `/reject_action`; deadline/reminder/Telegram project report extension (`connectors/action_deadline_report.py`); explicit reminder negation honoured; **language safety** layer (`connectors/action_language_safety.py`).
- **Executive Brief v3** (#70): executive signal discovery for constraints, logistics, commitments, status (`connectors/executive_signals.py`, `brief_signal_runtime.py`); `/brief` routed through StateStore; 06:45 travel rule; evidence-backed departure-time calculation.

---

## Phase 5 — Commerce, Bridge API & Books (1–4 Sep 2026)

- **1 Sep** — Capability Truth v2 (#71): read-only Main Sheet requests grounded. **Commerce Agent core** rebuilt on current Core Manager (#73): `connectors/commerce_agent.py`, trusted checkout adapter, read-only deal scout, safe sandbox smoke test, Telegram runtime (`/shop`, `/prepare_order`, `/approve_order`, `/commerce_status`, `/commerce_test`); **$100 pilot order and daily caps** with defense-in-depth.
- **2 Sep** — First-party **`/chat` Bridge API** protected by `BRIDGE_API_KEY` (`connectors/bridge_api.py`); unified ask via `ask_bedrock` alias.
- **3 Sep** — CI: manual isolated **strategic shadow DEV runner** (`.github/workflows/strategic-shadow-dev.yml`), safe prerequisite reporting, bounded concurrency.
- **4 Sep** — **Books context** module for the learning shelf (`engine/books_context.py`) → Super Manager integration → version bumps v2.0 → **v3.0** with enhanced retrieval; fast path for book queries in the Telegram bot (`/books`).

---

## Phase 6 — Master OS: Knowledge, Docs & Automation (8–9 Sep 2026) · AI OS v0.9 Master OS

### 8 Sep (#78)
- **Google Docs connector** (`connectors/google_docs_service.py`) + unified **connection status checker / doctor** (`connectors/connection_setup.py`, `docs/connection-guide.md`).
- Interactive **connection walkthrough page** (`docs/connection-walkthrough.html`: checkboxes, print/PDF, offline) with Buffer setup phase.
- Live bot gains sheet-tab creation and Google Docs creation (`tests/test_workspace_write_actions.py`).

### 9 Sep (#80–#83)
- **Master OS v0.9** (`docs/v0.9-master-os.md`, `engine/master_os.py`): standard Google Drive tree `Abdulrahman_Master_OS` (roots 01–05) + `engine/drive_tree.py render/checklist`.
- **Four sub-agents matrix** (Morning Briefing / Clinical & Ops / Knowledge & Audio / Finance & Life) + `prompts/master-os-agents.md`.
- **Automation scheduler** (`engine/scheduler.py`): 11 jobs — daily 06:45 / 07:30 / 16:00 / 20:30, weekly Sun/Tue/Thu/Fri, monthly 28th / 1st / last day, Asia/Riyadh — integrated with `manager --loop`; every run produces an approval-queue draft only. `scheduler.py today-actions` (DHS assignment 17 Sep, close NEEDS_INPUT, enable voice conversion).
- **Mind-map generator** (`engine/mindmap.py`): Markdown → Mermaid `mindmap` + text tree + `mind_maps` library; weekly Friday map.
- **Audio digest pipeline** (`engine/audio_digest.py`): QUEUED → DIGESTED → NARRATED, 5–7 min narrative script, mp3 via `ELEVENLABS_API_KEY`.
- Telegram Master OS panel: `/masteros`, `/schedule`, `/mind_maps`, `/audio_digests`, `/today_actions`, `/run`; CI compiles & gates `engine/telegram_bot.py`.
- **v0.9 live wiring** (#81, `docs/v0.9-live-wiring.md`): empty-state hardening for status/`telegram --test`; **ElevenLabs voice channel** in connection setup; `/diag` channel-status command (presence-only, offline).
- Fix (#82): Master OS commands & callbacks wired to the production webhook runtime.
- Fix (#83): Telegram reply noise removed — no routine footers, task-first brevity (`tests/test_telegram_response_policy.py`).
- Evaluation: `evaluation/master-os-adoption-v0.9.md`.

---

## Phase 7 — Proactive Chief of Staff & Content Engine (11–12 Sep 2026) · v1.0 → v1.0.3

### v1.0 — Proactive loop (#85, `docs/v1.0-proactive-chief-of-staff.md`, `engine/proactive.py`, 22 tests)
- Full loop **observe → remember → predict → score → decide → act/prepare/alert → learn** inside a single Store transaction, invoked from `manager --loop` (`PROACTIVE_ENABLED=0` to disable).
- **Open loops register** (`open_loops`): commitments to self / from others, renewals, decisions, project risks.
- **Autonomy ladder L0–L4 per category**: communications/money/legal/health/reputation → L0/L1 (prepare & suggest only); internal scheduling/reminders/tasks/prep → L2/L3 (reversible execution + report). No global "act freely" switch.
- **8 standing orders** (SO-001…008): meeting prep <30 min, appointment <48 h without window, rotting waiting-for, financial due <3 days, renewal <7 days, calendar conflict, travel <24 h, missed-commitment recovery; `order-disable SO-00x`.
- Missed-commitment recovery template: what was missed / impact / recovery options / what I did / what I need.
- Guards: confidence <0.8 → prepare not execute; **6 alerts/day** cap (overflow to brief); **quiet hours 22:00–06:30**; `undo PA-xxxx`; `pause --hours 4`; full audit log.
- Learning: `feedback PA-xxxx good|much|never`.
- **v1.0.1**: urgent-alert Telegram channel (`proactive_alert`) + first live sweep; `push-test`.
- **v1.0.2**: bot commands `/proactive`, `/sweep`, `/proactive_test`.
- **v1.0.3**: weekly acceptance review with bounded self-tuning of `PROACTIVE_CONFIDENCE_THRESHOLD` / `PROACTIVE_MAX_ALERTS` (`review --apply`, guard: ≥5 real decisions).
- CLI: `proactive.py sweep|brief|status|orders` → `reports/proactive-brief-YYYY-MM-DD.md`; prompt pack `prompts/proactive-chief-of-staff.md`.

### Publishing & content (11 Sep, #90–#99)
- **Buffer publisher** (`connectors/buffer_publisher.py`, GraphQL) with setup guide (`docs/buffer-setup.md`), status check, `--service` channel resolution, **Buffer Publish GitHub Action** (`.github/workflows/buffer-publish.yml`), PR-driven post queue (`posts/buffer/`); book-cover asset (`assets/`) scheduled for 20:00.
- **Production proactive worker** (`connectors/proactive_worker.py`): runs inside the Telegram webhook every 15 min (`PROACTIVE_WORKER_ENABLED`, `PROACTIVE_WORKER_INTERVAL_SECONDS`), records `last_proactive_worker`.
- **Content Creator orchestra** (researcher → critic → creator) (`connectors/content_creator.py`, `content_runtime.py`): `/content [platform] idea`, `/approve_content ID CODE`, `/reject_content ID`, `/content_status`; defaults `CONTENT_DEFAULT_PLATFORM=linkedin`, `BUFFER_DEFAULT_MODE=draft`.
- **Life Pulse publishing sheet** link (`connectors/content_sheet.py`): `/content_sheet Q-001`, `/content_sheet_status`, drafts written to `PUBLISH_QUEUE`.
- Robustness: keep workflow running on low OpenRouter credit (#97); recover safely from truncated Content Creator JSON (#98); publishing & proactive answers grounded in runtime truth (#99).

### 12 Sep
- **Gemini image & video workflow** for content (#100, `connectors/content_media.py`): `/design_content`, `/video_content`, `/media_status`; Sheet queue IDs accepted in media commands (#101).
- Fix (#102): books — tolerate learning-tab name variants, stop silent fall-through.

---

## Phase 8 — Production Hardening, Finance Hub & Autopay (14–15 Sep 2026) · v2.0 / v1.1

### 14 Sep (#103–#105)
- Fix: due scheduler jobs dispatched from the production webhook worker (#103).
- Fix: Riyadh scheduler persistence + **Google Drive project memory** (`connectors/project_memory.py`) (#104).
- Fix: production crash-loop stopped; **agent anchored to the real clock** (`engine/runtime_clock.py`, `docs/runtime-time-memory.md`) + `/time` liveness probe (#105).

### 15 Sep (#106–#108)
- **v2.0 Unified Finance Hub** (`engine/finance_hub.py`, `docs/FINANCE_HUB.md`): `finance` in StateStore as the single truth (`finance_ebsi` auto-migrated); external pull via secure webhook → public CSV → manual CSV; monthly snapshot (`reports/finance-monthly-YYYY-MM`) with `total_monthly/yearly`, `by_type`, `unused_count`, `savings_potential`, `health_index` (24 months retained); scheduled Thu 07:00, 1st 07:30, hourly throttled, 06:00 full cycle.
- **Dormant layer activation** (`docs/DORMANT_ACTIVATION_2026-09-15.md`): asset_registry, backup_verify, change_intelligence, observability, trust_dashboard now run in the manager loop — **14/14 layers active**; `engine/system_status.py --layers --schedule --finance --proactive` (`docs/SYSTEM_STATUS.md`).
- Proactive verification report (`docs/PROACTIVE_VERIFICATION_2026-09-15.md`); fix: proactive live context — no more INFERENCE/MISSING for finance/proactive; `system_status --layers` fixes bot MISSING for dormant/schedule.
- Sheet audit & master-sheet mirror (`docs/audits/`).
- **Verified YouTube search** (#107, `connectors/web_search.py`): `/youtube` (`/search`) returns only verified `watch?v=` links; automatic for messages requesting video links; DuckDuckGo default, optional `YOUTUBE_API_KEY`; PII stripped from queries; `python3 -m connectors.web_search --check`.
- **v1.1 Money threshold — autopay < 375 SAR** (#108, `docs/v1.1-money-threshold.md`, 18 tests, `scripts/verify_money_threshold.sh`): a single narrow exception to the "money is red" rule — commitments **< 375 SAR (~$100)** lift `money` from L1 → L3 (`ACT_PAY` / 🟩 GREEN) via `connectors/payment_gateway.py` with receipt, visible task, report and `undo` (refund request); ≥ 375 SAR or unknown amount stays 🟥 `ALERT_DRAFT`. Guards: `MONEY_AUTOPAY_ENABLED=1` + `MONEY_AUTOPAY_ACK=I_AUTHORIZE_SUB_375_SAR_AUTOPAY` + configured gateway + known positive amount + **daily cumulative cap 375** + idempotency key; `HARD_MAX_SAR = 375.00` in code (env can only lower it). Intent recorded `AUTHORIZED` inside the transaction, payment executed after commit; provider failure → fallback draft. New `autopay_executions` ledger + `autopay_*` audit events; `connectors/payment_sandbox.py`; CLI `proactive.py threshold|matrix|status`.

---

## Telegram command reference (cumulative, by introduction)

| Introduced | Commands |
|---|---|
| 22 Aug | `/start` `/help` `/profile` `/sources` `/selftest` `/okr` `/tasks` `/decisions` `/approve` `/door` `/mastery` `/reviews` `/answer` `/manager` `/manager_status` `/bedrock_test` `/context_test` |
| 24–25 Aug | `/brief` `/memory` `/memory_status` `/confirm_memory` `/update_memory` `/storage_status` |
| 28 Aug | `/delegate` `/agents` `/council` `/mission` `/google_access` |
| 30–31 Aug | `/manager_shadow` `/capabilities` `/act` `/action_status` `/approve_action` `/reject_action` |
| 1 Sep | `/shop` `/prepare_order` `/approve_order` `/commerce_status` `/commerce_test` |
| 4 Sep | `/books` |
| 9 Sep | `/masteros` `/schedule` `/mind_maps` `/mindmaps` `/digests` `/audio_digests` `/today_actions` `/run` `/diag` |
| 11 Sep | `/proactive` `/sweep` `/proactive_test` `/content` `/approve_content` `/reject_content` `/content_status` `/content_sheet` `/content_sheet_status` |
| 12 Sep | `/design_content` `/video_content` `/media_status` |
| 14–15 Sep | `/time` `/youtube` `/search` |

## Integrations (cumulative)

Telegram (polling → webhook) · AWS Bedrock (Claude, Nova Micro) · AWS Transcribe · OpenRouter · OpenAI GPT & Google Gemini (direct) · Google Sheets (service account, Apps Script webhook, direct) · Google Calendar · Google Drive · Google Docs · Gmail · GitHub · Railway (container + volume) · Buffer (GraphQL) · ElevenLabs · YouTube Data API / DuckDuckGo · Payment gateway webhook (sandboxed) · ChatGPT / VS Code bridge.

## Invariants that never changed

1. The engine **never sends an external side-effect** without passing the approval gate (SHA-256 hash, 48 h expiry, idempotent). The sole exception, v1.1 autopay < 375 SAR, is opt-in behind five independent guards and a hard cap in code.
2. **Clinical output is a hypothesis for human review**; no diagnosis from calls or pre-visit data; patient-identifiable information never enters general memory, Sheets summaries or GitHub.
3. StateStore is the **single writer**; Sheets are import/export mirrors.
4. Secrets live only in environment variables / platform secrets — never in the repository.

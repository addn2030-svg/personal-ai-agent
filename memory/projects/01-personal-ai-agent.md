# P1 · Personal AI Agent — Project Charter

| Field | Value |
|---|---|
| Project ID | `P1` |
| Name | Personal AI Agent |
| Status | `active` |
| Domain | Prompt engineering · custom agent frameworks |
| Owner | Abdulrahman Bakor Howsawy |
| Repository | `addn2030-svg/personal-ai-agent` (this repo) |
| Sensitivity | `internal` |
| Clinical project | No |
| Charter classification | `DOCUMENT` |
| Effective | 2026-09-22 |
| Last verified | 2026-09-22 |

---

## Scope

**In scope**

- Prompt-engineering assets: `prompts/*.md` command packs.
- Agent frameworks and runtimes: `engine/`, `connectors/`.
- Deterministic engines (rules/statistics) versus linguistic work (model calls),
  as split in `blueprint.md` §5.
- Evaluation, rollout gating and observability: `evaluation/`, `engine/rollout.py`,
  `engine/observability.py`.
- Workspace memory and routing: `root_memory.mmd`, `memory/`, `engine/memory_hub.py`.

**Out of scope**

- Curriculum production for P2 (see `memory/projects/02-telegram-ai-course.md`).
- Commercial rehabilitation operations for P3 (see
  `memory/projects/03-pulse-of-life-home-rehab.md`).
- Anything holding patient-identifiable clinical data — that class never enters
  this repository (`memory/GLOBAL_RULES.md` §3).

## Routing

| Target | Location | Purpose |
|---|---|---|
| Architecture blueprint | `blueprint.md` | Agent 0 + 6 skills model |
| System manual | `README.md` | Operating instructions |
| Prompt packs | `prompts/` | Paste-ready command bundles |
| Deterministic engines | `engine/` | Rules, statistics, scheduling |
| External connectors | `connectors/` | Telegram · Google · Supabase · Bedrock |
| Durable knowledge | `knowledge/` | Provenance-tagged source records |
| Governance | `docs/information-governance.md` | Record envelope + change policy |
| Hub validator | `engine/memory_hub.py` | Structural + language gates |
| Mutable state | `data/state.json` | Git-ignored, single-writer |

## Guardrails

1. **No secrets in Git.** Tokens, service-account JSON and `.env` values live in
   the environment only. `.gitignore` already excludes `secrets/`,
   `*.credentials.json`, `*.token.json`, `.env*`.
2. **No patient-identifiable clinical data in this repo.** De-identified case
   codes only, and only inside the restricted clinical boundary.
3. **External actions are approval-gated.** Anything that publishes, sends or
   spends goes through the approval queue with a content fingerprint.
4. **New layers run in parallel, never replace.** Follow the
   `dormant → shadow → canary → dual → primary` rollout in `docs/supabase-rollout.md`.
5. **Every durable fact carries provenance.** Source, classification,
   confidence, captured_at, last_verified — no exceptions.
6. **Deterministic before linguistic.** If a rule or a statistic can answer it,
   do not spend a model call.

## Current state

| Area | State | Evidence |
|---|---|---|
| Repo head | `636f5df` — Supabase layer merged | `git log` |
| Tests | 55 files under `tests/` | directory listing |
| Supabase rollout | Gated, staged, kill-switch available | `engine/rollout.py` |
| Workspace routing hub | Newly formalised as ABH-Memory | `root_memory.mmd` |
| Multi-project registry | 3 active projects registered | `engine/memory_hub.py` |

**Assumptions (labelled, per GLOBAL_RULES G6)**

- `ASSUMPTION-A1`: the three projects named in the owner's brief are the complete
  active set for this cycle; no dormant projects are registered.
- `ASSUMPTION-A2`: P2 and P3 do not yet have separate Git repositories; their
  routing target is a Notion workspace plus files inside this repo's `memory/`.

## Next actions

| # | Action | Owner | Due | Gate |
|---|---|---|---|---|
| P1-A1 | Confirm Notion database IDs for P1/P2/P3 and record them in each charter | Abdulrahman | 2026-09-27 | none |
| P1-A2 | Decide whether P2 and P3 get their own repositories or stay as `memory/` branches | Abdulrahman | 2026-09-30 | decision record |
| P1-A3 | Add the hub gate to `scripts/smoke_test.sh` — **DONE 2026-09-22** (runs pre-bootstrap for determinism) | Abdulrahman | closed | none |
| **P1-A5** | **Activate CI**: create `.github/workflows/ci.yml` from the staged `docs/ci-workflow.yml` template. Until this is done the hub gate is **not** enforced automatically — see `memory/README.md` | Abdulrahman | 2026-09-30 | owner decision — turns on automated runs repo-wide |
| P1-A4 | Register dormant projects when they resume | Abdulrahman | rolling | none |

## Risk notes

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| P1-R1 | Hub map drifts from the real project set; routing becomes misleading | Medium | Medium | `engine/memory_hub.py` V3/V4 gates run in CI |
| P1-R2 | A secret or credential is committed during rapid iteration | Low | High | `.gitignore` coverage + V7 privacy scan on hub artefacts |
| P1-R3 | Patient-identifiable data leaks in from P3 work into P1 files | Low | Critical | Hard boundary in GLOBAL_RULES §3; V7 scan; clinical data stays in the restricted store |
| P1-R4 | Assumption A2 proves wrong and charters point at non-existent repos | Medium | Low | Verify Notion/repo targets in P1-A1 before external reference |

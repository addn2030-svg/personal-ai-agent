# ABH-Memory — Workspace Hub

A **multi-project routing and governance hub** for a personal and professional
workspace managed through Git and Notion. The hub answers one question before any
work starts: *which project is this, what rules apply to it, and where does the
artefact live?*

| Field | Value |
|---|---|
| Hub root map | `root_memory.mmd` (Mermaid mindmap) |
| Binding rule set | `memory/GLOBAL_RULES.md` |
| Project registry | `engine/memory_hub.py` → `PROJECTS` |
| Validator | `python3 -m engine.memory_hub validate` |
| Tests | `tests/test_memory_hub.py` |
| Established | 2026-09-22 |
| Owner | Abdulrahman Bakor Howsawy |

---

## Active projects

| ID | Project | Domain | Charter | Sensitivity | Current sprint |
|---|---|---|---|---|---|
| `P1` | Personal AI Agent | Prompt engineering · custom agent frameworks | `memory/projects/01-personal-ai-agent.md` | internal | — |
| `P2` | Telegram AI Course | Educational content · curriculum design | `memory/projects/02-telegram-ai-course.md` | internal | — |
| `P3` | Pulse of Life Rehab & Home Visit | Jubail home-visit pilot · NKT/ANF · marketing ops | `memory/projects/03-pulse-of-life-home-rehab.md` | **clinical-adjacent** | `memory/sprints/2026-W39-pulse-of-life-home-visit.md` |
| `P4` | ABH-Memory Hub | Multi-project routing · governance gates · sprint oversight | `memory/projects/04-abh-memory-hub.md` | internal | — |

Dormant projects: none registered this cycle.

## Layout

```text
root_memory.mmd                        ← hub root map (Mermaid mindmap)
memory/
├── README.md                          ← this file
├── GLOBAL_RULES.md                    ← binding rules for every project
├── projects/
│   ├── 01-personal-ai-agent.md        ← P1 charter
│   ├── 02-telegram-ai-course.md       ← P2 charter
│   ├── 03-pulse-of-life-home-rehab.md ← P3 charter (clinical guardrails)
│   └── 04-abh-memory-hub.md           ← P4 charter (hub self-governance)
└── sprints/
    └── 2026-W39-pulse-of-life-home-visit.md  ← P3 execution roadmap
engine/memory_hub.py                   ← routing · envelope · governance gates
tests/test_memory_hub.py               ← hub regression tests
```

The hub **adds** a routing and governance layer. It does not replace anything:

| Existing component | Still authoritative for |
|---|---|
| `data/state.json` | Operational mutable state (single-writer) |
| `data/audit.jsonl` | Audit and change events |
| `engine/memory.py` | Working · episodic · semantic memory layers |
| `connectors/project_memory.py` | Guarded Google Docs project memory |
| `docs/information-governance.md` | Record envelope and change policy |
| `knowledge/` | Provenance-tagged durable knowledge |
| `blueprint.md` | Agent 0 + 6 skills architecture |

## Charter contract

Every project charter must declare these four sections or the validator fails it
(gate `V5`):

1. **Scope** — in scope, out of scope, hard exclusions
2. **Guardrails** — binding rules specific to that project
3. **Current state** — with a classification per row
4. **Next actions** — owner and date on every action

Charters also carry a routing table, labelled assumptions, and a risk register.

## Governance gates

`python3 -m engine.memory_hub validate` runs eight fail-closed gates:

| Gate | Checks | Failure means |
|---|---|---|
| `V1` | `root_memory.mmd` parses as a Mermaid mindmap | Hub root map is corrupt or missing |
| `V2` | Every in-repo path referenced by the hub exists | Dangling reference — routing is misleading |
| `V3` | Every registered project appears in the hub map | Registry and map have drifted apart |
| `V4` | Every active project has a charter on disk | Project is routed but undocumented |
| `V5` | Charters declare Scope · Guardrails · Current state · Next actions | Charter is incomplete |
| `V6` | No medical guarantee or exaggerated claim language in hub artefacts | `GLOBAL_RULES` §2 breached |
| `V7` | No patient-identifiable data or secrets in hub artefacts | `GLOBAL_RULES` §3 breached |
| `V8` | Global rules declare the clinical and privacy boundary | Rule set incomplete |

Exit code `0` = all gates pass. Exit code `1` = action required before publishing
or committing hub artefacts.

The gate is wired into `scripts/smoke_test.sh`, which executes
`memory_hub validate` and `tests/test_memory_hub.py` **before** the demo
bootstrap, so results stay deterministic and independent of runtime state.

> **CI status — read this before relying on automation.** `docs/ci-workflow.yml`
> is a *staged template*, not an active workflow. Per `README.md`
> (§"تفعيل اختبار CI"), CI activates only when the owner creates
> `.github/workflows/ci.yml` with that content. No active workflow currently
> invokes `scripts/smoke_test.sh`, so **the gate is not yet enforced
> automatically**. Until CI is activated, run it explicitly:
>
> ```bash
> python3 -m engine.memory_hub validate
> python3 tests/test_memory_hub.py
> ```
>
> Verify rather than assume: `gh pr checks <n>` should list a `smoke` check once
> CI is live.

### Claim guardrail (gate V6)

Seven pattern classes are detected: cure/elimination promises, certainty and
guarantee language, fixed recovery timelines, superiority rankings,
reversal/regeneration claims, unverified endorsements, and outcome promises tied
to a named condition. The scan **reports** candidates for human review; it never
rewrites text. A false positive costs a read. A false negative costs a regulatory
exposure.

### Privacy guardrail (gate V7)

Detects MRN references, national ID / iqama references, named-patient labels,
contact numbers in a clinical context, and credential literals.

Exemptions: `memory/GLOBAL_RULES.md` and `engine/memory_hub.py` legitimately
**quote** prohibited language in order to forbid it, so they are excluded from
the scan by `SCAN_EXEMPT`.

## Commands

```bash
python3 -m engine.memory_hub route             # project routing table (JSON)
python3 -m engine.memory_hub validate          # run all eight gates
python3 -m engine.memory_hub validate --json   # machine-readable report
python3 -m engine.memory_hub scan FILE [...]   # guardrail scan on any artefact
python3 -m engine.memory_hub envelope \
    --project P3 --type DECISION \
    --source "regulatory check 2026-09-23" \
    --summary "home delivery position" --confidence VERIFY
```

## Adding a project

1. Add the record to `PROJECTS` in `engine/memory_hub.py`.
2. Create `memory/projects/NN-<slug>.md` with the four required sections.
3. Add the branch to `root_memory.mmd` using the established format:
   `Pn · Name` as a sub-branch, with `Charter <path>` as a leaf.
4. Run `python3 -m engine.memory_hub validate` — it must pass.
5. Add a test to `tests/test_memory_hub.py`.

## Adding a sprint

1. Create `memory/sprints/YYYY-Www-<project-slug>.md`.
2. Reference it from the project charter and from `root_memory.mmd`.
3. Every sprint must contain: rules acknowledgement, gates, sequenced daily plan,
   per-day checklists, explicit exclusions, risk register, next actions with
   owners and dates, and exit criteria.
4. Run the validator.

## Provenance

Every durable record produced through the hub carries the envelope from
`docs/information-governance.md`: record ID, type, source, captured_at, effective
date, last verified, confidence class, owner, related project, status, next
action, due date, sensitivity.

Record types: `FACT` · `USER_STATEMENT` · `DOCUMENT` · `AI_INFERENCE` ·
`RECOMMENDATION` · `REQUEST` · `DECISION`

Confidence classes: `CONFIRMED` · `DOCUMENT_SUPPORTED` · `INFERRED` · `VERIFY` ·
`HISTORICAL`

**Rule:** a web source older than 24 months on a regulatory question is a *lead*,
not evidence. Cite the primary instrument or obtain professional advice.

## Notion bridge

Notion is the human-facing view; Git is the versioned source of truth.

| Direction | Content | Rule |
|---|---|---|
| Git → Notion | Charters, sprint plans, gate status, decision log | Mirror after each checkpoint; record the Notion database ID in the charter |
| Notion → Git | New durable decisions, confirmed facts | Import with a provenance envelope; never import identifiers or secrets |
| Never either way | Patient-identifiable clinical data, credentials | Hard boundary — restricted clinical store only |

Notion database IDs for P1/P2/P3 are currently `VERIFY` (not recorded). Actions
`P1-A1`, `P2-A1` and `P3-A1` close this gap.

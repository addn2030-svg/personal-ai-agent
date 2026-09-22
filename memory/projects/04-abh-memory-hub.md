# P4 · ABH-Memory Hub — Project Charter

| Field | Value |
|---|---|
| Project ID | `P4` |
| Name | ABH-Memory Hub |
| Status | `active` |
| Domain | Multi-project routing · governance gates · hub artefacts and sprint oversight |
| Owner | Abdulrahman Bakor Howsawy |
| Repository | `addn2030-svg/personal-ai-agent` (this repo) |
| Sensitivity | `internal` |
| Clinical project | No — but the artefacts it tracks include the clinical-adjacent P3 sprint, whose full boundary applies to any edit of those files |
| Charter classification | `DOCUMENT` |
| Effective | 2026-09-22 |
| Last verified | 2026-09-22 |

**Why this project is registered.** The hub is the layer every other project is
routed through: registry, root map, provenance envelope, and the V1–V8 gates.
Registering it as `P4` puts hub-layer work itself under the same audit discipline
it enforces — changes to routing, gates and hub artefacts now travel with a
charter, a risk register and next actions, like everything else.

---

## Scope

**In scope**

- The machine-readable routing registry: `PROJECTS` in `engine/memory_hub.py`.
- The human-readable hub root map: `root_memory.mmd`.
- The binding rule set and its documentation: `memory/GLOBAL_RULES.md`,
  `memory/README.md`.
- The charter and sprint conventions: `memory/projects/`, `memory/sprints/`.
- The provenance envelope API (`engine.memory_hub envelope`) and its closed
  vocabularies for record types and confidence classes.
- The validation gates V1–V8 and the hub test suite `tests/test_memory_hub.py`.
- Gate wiring in `scripts/smoke_test.sh` (runs pre-bootstrap for determinism).
- Oversight of published sprint artefacts — currently
  `memory/sprints/2026-W39-pulse-of-life-home-visit.md` (P3's execution roadmap).

**Out of scope**

- Clinical content authoring and any patient-facing decision — owned by P3,
  human clinician only (`memory/GLOBAL_RULES.md` §6).
- Course production (P2) and agent runtime engineering (P1).
- Rewriting scanned text: the guardrail scan **reports** candidates; it never
  edits copy (documented behaviour of `scan_text`).
- Anything holding patient-identifiable data — hard boundary,
  `memory/GLOBAL_RULES.md` §3; that data class never enters this repository.

**Hard exclusions**

- Weakening a gate (thresholds, exemptions, scan patterns) as a side effect of
  unrelated work. `SCAN_EXEMPT` stays closed: `memory/GLOBAL_RULES.md` and
  `engine/memory_hub.py` only.
- Committing runtime state (`data/`) or any secret — the V2/WARN split exists to
  keep that boundary honest.
- Promoting a hub change without the gates re-run on the final tree.

## Routing

| Target | Location | Purpose |
|---|---|---|
| Routing registry | `engine/memory_hub.py` → `PROJECTS` | Machine-readable project set (source of truth) |
| Hub root map | `root_memory.mmd` | Human-readable routing view (validated against the registry by V3) |
| Global rules | `memory/GLOBAL_RULES.md` | Binding rules for every project |
| Project charters | `memory/projects/01…04` | One contract per project (V5) |
| Sprint artefacts | `memory/sprints/` | Time-boxed execution plans |
| Envelope specification | `docs/information-governance.md` | Provenance fields for durable records |
| Validator | `python3 -m engine.memory_hub validate` | All eight gates, fail-closed |
| Hub tests | `tests/test_memory_hub.py` | Regression coverage for routing, envelope, gates |
| Smoke wiring | `scripts/smoke_test.sh` | Gate + tests run before the demo bootstrap |
| Hub documentation | `memory/README.md` | Layout, contracts, commands, Notion bridge |

## Guardrails

1. **Fail-closed, always.** An unreadable hub map, a missing charter or a
   dangling reference is a FAIL, never a silent pass. A change that turns a gate
   from FAIL into WARN without a recorded decision is rejected.
2. **The scan reports; it never rewrites.** A false positive costs a read; a
   false negative costs regulatory exposure. Both directions are reviewed by a
   human — external clinical or marketing text additionally needs recorded
   specialist sign-off (`memory/GLOBAL_RULES.md` §6).
3. **Registry and map must not drift.** Any edit to `PROJECTS` lands in the same
   change as its `root_memory.mmd` branch; gate V3 enforces, the hub test
   `test_every_registered_project_in_hub_map` covers it from the other side.
4. **Charter contract.** Four required sections (Scope · Guardrails · Current
   state · Next actions), a routing table, labelled assumptions and a risk
   register — V5 plus the charter tests, applied to `P4` itself.
5. **Clinical boundary is inherited, not diluted.** Edits to P3 sprint or
   charter artefacts run the V6/V7 scans with zero findings required; prohibition
   lines and quoted counter-examples remain the only documented exemptions.
6. **Every durable artefact carries the envelope.** Record ID, type, source,
   confidence, owner, related project, status, next action — built with
   `python3 -m engine.memory_hub envelope`, never hand-forged vocabulary.
7. **Self-reference control.** The hub governs the hub: any change to gate logic
   must keep `tests/test_memory_hub.py` green on the final tree, and the tests
   themselves are the check that a gate still fails when it should.

## Current state

| Area | State | Classification | Evidence |
|---|---|---|---|
| Hub layer | Merged to `main` — PR #116, commit `e4a7ed1`, 2026-09-22 | `FACT` · CONFIRMED | `git log` |
| Gates | 8/8 passing at P4 registration | `FACT` · CONFIRMED | `python3 -m engine.memory_hub validate` |
| Registry | 4 active projects (P1–P4), none dormant this cycle | `FACT` · CONFIRMED | `engine/memory_hub.py` |
| CI enforcement | Staged template only — no active workflow runs the gate automatically | `FACT` · DOCUMENT_SUPPORTED | `memory/README.md` §CI status; `docs/ci-workflow.yml` |
| Notion bridge | Database IDs for P1–P4 not recorded; mirror pending | `DOCUMENT` · VERIFY | actions `P1-A1`, `P4-A2` |
| P3-W39 oversight | Sprint artefacts published; Tue 2026-09-22 is working day 1 of 3; no paid home visit in this window | `DOCUMENT` · DOCUMENT_SUPPORTED | `memory/sprints/2026-W39-pulse-of-life-home-visit.md` |

**Assumptions (labelled, per GLOBAL_RULES G6)**

- `ASSUMPTION-A1`: P4 owns the hub's policy and artefact discipline; code
  changes to `engine/memory_hub.py` still follow P1's engineering conventions
  (tests + PR in this repository). Registration adds auditability, it does not
  move ownership.
- `ASSUMPTION-A2`: this charter was established from the owner's brief of
  2026-09-22; the three pre-existing projects remain the complete non-hub active
  set for this cycle.
- `ASSUMPTION-A3`: the hub map and registry remain the routing truth; Notion is
  a view. If a mirror exists only in Notion, it is not yet a durable record.

## Next actions

| # | Action | Owner | Due | Gate |
|---|---|---|---|---|
| P4-A1 | Run `python3 -m engine.memory_hub validate` at the start and end of each remaining sprint day (Tue–Thu) and note the result in the sprint file | Abdulrahman | 2026-09-24 | none |
| P4-A2 | Record the Notion database ID of the hub view (after `P1-A1` closes) in this charter and in `memory/README.md` | Abdulrahman | 2026-09-27 | decision record |
| P4-A3 | Activate CI (cross-ref `P1-A5`): create `.github/workflows/ci.yml` from `docs/ci-workflow.yml`; verify `gh pr checks <n>` lists the smoke check | Abdulrahman | 2026-09-30 | owner decision — enables automated runs repo-wide |
| P4-A4 | At the Sun 2026-09-27 sprint checkpoint, confirm every artefact produced during the week carries a provenance envelope | Abdulrahman | 2026-09-27 | none |
| P4-A5 | Sprint retro: re-scan all hub artefacts (V6/V7) and record zero-findings status in this charter's Current state | Abdulrahman | 2026-09-27 | none |

## Risk notes

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| P4-R1 | Self-referential governance: a gate change silently weakens enforcement | Low | High | Guardrail 7; tests assert fail-closed behaviour on the final tree; smoke gate runs pre-bootstrap |
| P4-R2 | Registry and hub map drift apart as projects change | Medium | Medium | V3 plus `test_every_registered_project_in_hub_map`; this charter's Routing table mirrors both |
| P4-R3 | The prohibition-line heuristic exempts a real claim hidden in governance text | Low | High | Heuristic is narrow, documented beside the code; human review of any external copy remains mandatory (§6) |
| P4-R4 | Sprint oversight goes stale — gates skipped during a busy P3 week | Medium | Medium | `P4-A1` day checklist; `P4-A3` makes every PR run them automatically |
| P4-R5 | CI is not active, so enforcement depends on explicit runs | High (known) | Medium | `P4-A3`; `memory/README.md` states "verify rather than assume" until a smoke check appears on PRs |

## Provenance

No new external facts are asserted by this charter. Every Current state row
cites repository evidence; the Notion and CI rows carry `VERIFY` /
`DOCUMENT_SUPPORTED` because they describe absence of a record, not a verified
target. Durable decisions produced through the hub use the envelope builder and
reference `P4`.

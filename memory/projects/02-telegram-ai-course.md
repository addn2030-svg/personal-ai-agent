# P2 · Telegram AI Course — Project Charter

| Field | Value |
|---|---|
| Project ID | `P2` |
| Name | Telegram AI Course |
| Status | `active` |
| Domain | Educational content creation · curriculum design |
| Owner | Abdulrahman Bakor Howsawy |
| Repository | none yet — see `ASSUMPTION-A2` in P1 charter |
| Notion target | `VERIFY` — database ID not yet recorded |
| Sensitivity | `internal` |
| Clinical project | No |
| Charter classification | `DOCUMENT` |
| Effective | 2026-09-22 |
| Last verified | 2026-09-22 |

---

## Scope

**In scope**

- Curriculum architecture: modules, sequencing, learning objectives, assessments.
- Educational content production: lessons, exercises, worked examples.
- Teaching methodology already adopted in this workspace — the ILPC method
  (EAT + CPR + 90/20/8) documented in `prompts/personal-training.md` and
  `blueprint.md` §4.
- Delivery mechanics on Telegram: lesson drops, bot interaction patterns,
  learner feedback loops — reusing `connectors/telegram_bot.py` patterns.
- Publication pipeline: `posts/`, `connectors/buffer_publisher.py`.

**Out of scope**

- Selling clinical services or booking patients (that is P3).
- Any learner-facing medical advice. The course teaches **AI and automation
  technique**, not diagnosis or treatment.
- Use of employer-confidential material as course content (see Guardrails §3).

## Routing

| Target | Location | Purpose |
|---|---|---|
| Teaching protocol | `prompts/personal-training.md` | Mandatory ILPC delivery rules |
| Teaching adoption record | `evaluation/teaching-protocol-adoption.md` | Why the protocol is binding |
| Course-adjacent material | `materials/` | Prepared teaching assets |
| Telegram delivery patterns | `connectors/telegram_bot.py` | Bot interaction reference |
| Publishing pipeline | `connectors/buffer_publisher.py` | Scheduled distribution |
| Draft posts | `posts/buffer/` | Content queue |

## Guardrails

1. **No clinical instruction to learners.** If a lesson example touches
   rehabilitation, it uses synthetic or fully de-identified cases and states that
   it is illustrative, not a treatment protocol.
2. **No guarantees about learner outcomes.** Do not promise employment, income,
   certification or skill level. Permitted framing: what the module covers and
   what the learner will practise.
3. **No employer-confidential material.** RCJY/RCHSP internal documents, pricing,
   staff data and patient-adjacent records are never used as course content
   (`memory/GLOBAL_RULES.md` §5).
4. **Attribution and licensing.** Third-party material carries source and licence.
   Do not redistribute paid or proprietary content.
5. **Every published lesson is reviewed before release** and the review is
   recorded, per GLOBAL_RULES §6.
6. **Claims about AI capability stay current-dated.** Model names, limits and
   pricing change; each lesson carries a `last_verified` date.

## Current state

| Area | State | Evidence |
|---|---|---|
| Curriculum outline | `VERIFY` — not found in this repository | repo scan 2026-09-22 |
| Teaching methodology | Adopted and binding (ILPC) | `prompts/personal-training.md` |
| Delivery channel | Telegram patterns available | `connectors/telegram_bot.py` |
| Notion database | Not yet linked to this hub | `ASSUMPTION-A2` |
| Learner cohort | Not registered | — |

**Assumptions (labelled, per GLOBAL_RULES G6)**

- `ASSUMPTION-B1`: the course exists in Notion and possibly other tooling not
  mirrored into this repository; the charter therefore records routing gaps
  rather than claiming the project is unstarted.
- `ASSUMPTION-B2`: the target audience is Arabic-speaking professionals learning
  applied AI, consistent with the workspace's bilingual conventions.

## Next actions

| # | Action | Owner | Due | Gate |
|---|---|---|---|---|
| P2-A1 | Record the Notion database ID and course URL in this charter | Abdulrahman | 2026-09-27 | none |
| P2-A2 | Mirror the current curriculum outline into `memory/projects/p2-outline.md` | Abdulrahman | 2026-10-04 | none |
| P2-A3 | Draft an outcome-language policy for marketing the course (no income or job promises) | Abdulrahman | 2026-10-04 | specialist review |
| P2-A4 | Decide repository strategy (standalone repo vs. `memory/` branch) | Abdulrahman | 2026-09-30 | decision record |

## Risk notes

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| P2-R1 | Course marketing drifts into income or employment promises | Medium | High | Guardrail §2 + claim scan before any publish |
| P2-R2 | Employer-confidential material used as a teaching example | Low | Critical | Guardrail §3; role-separation rule GLOBAL_RULES §5 |
| P2-R3 | Lessons teaching model capability go stale as products change | High | Medium | `last_verified` stamp on every lesson |
| P2-R4 | Curriculum lives only in Notion, so the hub cannot validate it | Medium | Medium | P2-A2 mirror step |
| P2-R5 | A clinical example is read by a learner as treatment advice | Low | High | Guardrail §1; synthetic cases only |

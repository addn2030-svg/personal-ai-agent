# ABH-Memory — Global Operating Rules

> **Scope:** every project, every agent run, every artefact produced inside this
> workspace. These rules are **binding**, not advisory. Where a project charter
> conflicts with this file, **this file wins**.

Classification: `GOVERNANCE` · Owner: Abdulrahman Bakor Howsawy · Effective: 2026-09-22
Last verified: 2026-09-22 · Review cadence: monthly

---

## 1. Voice and output standards

| # | Rule | Enforcement |
|---|---|---|
| G1 | Maintain a **professional, structured, clinical, actionable** tone. | Reviewer reads output; no casual filler. |
| G2 | Use **Markdown tables** for any comparison of two or more options. | Any comparison rendered as prose is rejected. |
| G3 | Use **bullet points or numbered lists** for steps and procedures. | Steps never rendered as paragraphs. |
| G4 | Every plan carries an **explicit risk note** section. | Missing risk section = incomplete deliverable. |
| G5 | Every plan ends with **clear next actions** (owner + date). | "TBD" owners are not accepted. |
| G6 | State **assumptions explicitly** and label them as assumptions. | Assumption presented as fact = governance defect. |

## 2. Clinical and marketing claims — hard boundary

**Zero medical guarantees. Zero exaggerated claims.** This applies to
rehabilitation content, marketing copy, social posts, course material, and any
patient-facing or public-facing text.

| Prohibited pattern class | Examples (non-exhaustive) | Permitted replacement |
|---|---|---|
| Cure / elimination promises | "cures", "eliminates pain", "permanent fix" | "may support", "commonly used for" |
| Certainty language | "guaranteed", "100%", "proven to heal" | "individual results vary" |
| Fixed recovery timelines | "recover in 2 weeks", "healed in 6 sessions" | "a typical course is 6 sessions; response varies" |
| Superiority / comparative claims | "best in Jubail", "better than hospital care" | describe the service, do not rank it |
| Outcome guarantees for a named condition | "reverses stroke damage" | "supports functional retraining" |
| Unverified endorsement | "RCJY-approved home service" | only if written approval is on file |

- Any claim of clinical effect must be **hedged** and attributed to the
  clinician's professional judgement, never presented as a predicted result.
- Package names, prices and session counts sourced from
  `knowledge/rcjy-rehabilitation-service-packages.md` are **planning-document
  facts**, not evidence of current operational approval or current billing
  policy. Verify before external use.
- All externally published clinical or marketing text requires **recorded
  specialist approval** before release.

## 3. Privacy and data boundaries

| Data class | Permitted location | Never |
|---|---|---|
| Patient-identifiable clinical data (name, MRN, national ID, contact, identifying free text) | Approved restricted clinical store only | Git · general agent memory · Telegram · marketing assets |
| De-identified case reference | Clinical spreadsheet + agent memory | Public artefacts |
| Personal contact data (`PRIVATE_CONTACT`) | `knowledge/master-professional-profile.yaml` | Public posts, screenshots, shared decks |
| Professional identifier (SCFHS licence ref.) | Profile file | Marketing copy, social posts |
| Secrets, tokens, service-account JSON | Environment / local secret store | Git, in any form, ever |

- The **pre-visit boundary** in `docs/information-governance.md` applies to
  Project 03 in full: clinic-issued case codes only, no identifiers in Telegram,
  GitHub, or general memory.
- Google Forms are **link-access forms**, not per-patient authenticated portals.
  Do not describe them as secure patient portals.

## 4. Provenance and classification

Every durable fact, request or decision carries the record envelope defined in
`docs/information-governance.md`. Classification vocabulary:

`FACT` · `USER_STATEMENT` · `DOCUMENT` · `AI_INFERENCE` · `RECOMMENDATION` ·
`REQUEST` · `DECISION`

Confidence classes: `CONFIRMED` · `DOCUMENT_SUPPORTED` · `INFERRED` · `VERIFY` ·
`HISTORICAL`.

- **No durable identity fact without source, confidence and verification status.**
- User-confirmed facts override older conflicting drafts, but the **conflict
  history is preserved**, not deleted.
- Regulatory statements produced by an agent are classified `AI_INFERENCE` with
  status `VERIFY` until confirmed against a primary source. They are never
  recorded as `FACT`.

## 5. Separation of roles — conflict-of-interest control

Abdulrahman holds a **senior employed leadership role** (Head of Rehabilitation,
RCHSP Jubail) and **private commercial projects**. These are distinct streams.

- No employer asset, patient list, internal document, staff directory, pricing
  data or confidential plan may be used to benefit a private project.
- Private-project marketing must not imply employer endorsement, affiliation or
  referral relationships unless documented written approval exists.
- Where a private pilot could compete with or draw from the employer's service
  line, the **conflict must be declared and cleared in writing** before external
  activity begins.
- Working time, employer devices and employer credentials are not used for
  private-project execution.

## 6. Action gating

| Action type | Gate |
|---|---|
| Read / analyse / draft internally | No gate |
| Write to durable memory or knowledge | Provenance envelope required |
| Publish externally (social, site, marketplace) | Recorded specialist + owner approval |
| Send anything patient-facing | Recorded clinician approval |
| Financial or contractual commitment | Explicit owner approval, amount-stamped |
| Clinical decision on an identified patient | Human clinician only — never delegated to an agent |

## 7. Escalation triggers

Raise a `REVIEW_REQUIRED` record and stop work when any of these occur:

- New evidence contradicts an active state, decision or published claim.
- A regulatory requirement is discovered that blocks a planned activity.
- A privacy boundary has been or may have been crossed.
- A request has no identified owner after triage.
- A deliverable cannot meet rule G2–G5 without inventing information.

---

## Compliance self-check (run before publishing any deliverable)

- [ ] Comparisons are in tables (G2)
- [ ] Steps are in lists (G3)
- [ ] Explicit risk notes present (G4)
- [ ] Next actions have owners and dates (G5)
- [ ] Assumptions labelled (G6)
- [ ] Zero guarantees, zero exaggeration (§2)
- [ ] No patient-identifiable data (§3)
- [ ] Every factual claim has source + classification (§4)
- [ ] Role separation respected (§5)
- [ ] Required approvals recorded (§6)

Automated gate: `python3 -m engine.memory_hub validate`

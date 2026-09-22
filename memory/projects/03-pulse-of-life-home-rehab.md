# P3 · Pulse of Life Rehab & Home Visit — Project Charter

| Field | Value |
|---|---|
| Project ID | `P3` |
| Name | Pulse of Life Advanced Home Rehabilitation |
| Status | `active` — pre-launch pilot |
| Domain | Jubail home-visit pilot · NKT/ANF protocols · marketing ops |
| Owner | Abdulrahman Bakor Howsawy |
| Repository | none yet — see `ASSUMPTION-A2` in P1 charter |
| Notion target | `VERIFY` — database ID not yet recorded |
| Sensitivity | `clinical-adjacent` |
| Clinical project | **Yes** — all clinical guardrails apply |
| Charter classification | `DOCUMENT` |
| Effective | 2026-09-22 |
| Last verified | 2026-09-22 |
| Current sprint | `memory/sprints/2026-W39-pulse-of-life-home-visit.md` |

---

## Scope

**In scope**

- Private, home-based rehabilitation service pilot in Jubail Industrial City.
- Service design: assessment pathway, session structure, protocol selection
  (NKT, ANF, Mulligan/CMPT, myofascial needling, lymphedema MLD/CDT) as
  practitioner-held competencies recorded in
  `knowledge/master-professional-profile.yaml`.
- Package and pricing design, benchmarked against — **not copied from** —
  `knowledge/rcjy-rehabilitation-service-packages.md`.
- Marketing operations: positioning, compliant copy, channel selection, referral
  development.
- Operational readiness: legal form, licensing, consent, documentation,
  infection control, sharps handling, transport, equipment, insurance.
- Pilot measurement: enrolment, retention, satisfaction, session completion.

**Out of scope — hard exclusions**

- Any use of the employer's patient lists, referral queues, staff, scheduling
  system, internal documents, pricing or facilities.
- Any public claim of employer endorsement, affiliation or partnership.
- Any agent-executed clinical decision on an identified patient.
- Hydrotherapy in the home setting (excluded in the reference package framework
  and impractical for home delivery).
- Publishing patient-identifiable material in any channel, including testimonials
  with names, photos, addresses or contact details.

## Routing

| Target | Location | Purpose |
|---|---|---|
| Current sprint plan | `memory/sprints/2026-W39-pulse-of-life-home-visit.md` | This week's execution roadmap |
| Global rules | `memory/GLOBAL_RULES.md` | Claim + privacy + role-separation boundary |
| Information governance | `docs/information-governance.md` | Record envelope, pre-visit clinical boundary |
| Practitioner competencies | `knowledge/master-professional-profile.yaml` | What may legitimately be offered |
| Employer work context | `knowledge/rcjy-rehabilitation-work-context.md` | Role-separation source |
| Reference package framework | `knowledge/rcjy-rehabilitation-service-packages.md` | Benchmark only — planning-document facts |
| Pre-visit form pattern | `connectors/previsit_patient_form.gs` | Intake pattern reference |
| Clinical sheet pattern | `connectors/clinical_sheet.py` | Restricted clinical store pattern |
| Pre-visit intelligence | `engine/previsit_intelligence.py` | Conservative triage for clinician review |
| Hub validator | `engine/memory_hub.py` | Claim + privacy gates on P3 artefacts |

## Guardrails

These are **binding** and are enforced mechanically by `engine/memory_hub.py`
(gates V6 and V7) on every P3 artefact.

1. **Zero medical guarantees. Zero exaggerated claims.** No cure language, no
   certainty language, no fixed recovery timelines, no superiority rankings, no
   reversal claims. Full pattern table in `memory/GLOBAL_RULES.md` §2.
2. **Role separation is a precondition, not a preference.** The employed
   leadership role and this private pilot are distinct streams. Written conflict
   clearance must exist **before** any external marketing activity
   (`memory/GLOBAL_RULES.md` §5).
3. **Regulatory status is verified before operation, not after.** No home visit
   is delivered for payment until the legal form, professional practice
   permissions and any required facility or home-care authorisation are
   confirmed in writing against primary sources.
4. **Referral pathway respected.** Direct-access physiotherapy is restricted in
   KSA; a referral or physician relationship is part of the intake design, not an
   optional extra. Status `VERIFY` — confirm current rule with a primary source.
5. **Patient data never enters this repository.** Case codes only, inside the
   restricted clinical store. Nothing identifying in Git, Telegram, marketing
   assets or general agent memory.
6. **Home-setting safety is designed in.** Infection prevention, sharps
   containment and disposal, emergency escalation, lone-worker safety, and a
   documented home-environment suitability check before the first visit.
7. **Invasive techniques carry explicit consent and home-setting review.**
   Needling-based approaches require documented informed consent, a home
   feasibility assessment, and a decision on whether the technique is appropriate
   outside a clinical facility at all.
8. **Published copy is reviewed before release** and the review is recorded.
9. **No agent autonomy on clinical decisions.** Agents may draft, organise and
   remind. The clinician decides.

## Current state

| Area | State | Evidence | Classification |
|---|---|---|---|
| Practitioner licensure | Active SCFHS licence recorded | `master-professional-profile.yaml` | `CONFIRMED` |
| Practitioner competencies (NKT, ANF, CMPT, MLD/CDT, needling) | Recorded from user-confirmed CV | same | `CONFIRMED` |
| Prior private home-based PT operations | Managed previously, per CV | same | `USER_STATEMENT` |
| Reference package framework (16 packages, 6×45–60 min, 1,600–2,800 SAR) | October 2025 planning document | `rcjy-rehabilitation-service-packages.md` | `DOCUMENT` |
| Legal entity for the pilot | Not recorded in this workspace | repo scan 2026-09-22 | `VERIFY` |
| Home-care / facility authorisation for private practice | Not recorded | repo scan 2026-09-22 | `VERIFY` |
| Employer conflict-of-interest clearance | Not recorded | repo scan 2026-09-22 | `VERIFY` |
| Liability / professional indemnity cover for home visits | Not recorded | repo scan 2026-09-22 | `VERIFY` |
| Marketing assets | None found in this workspace | repo scan 2026-09-22 | `FACT` |
| Pilot cohort / enrolled cases | None recorded | repo scan 2026-09-22 | `FACT` |
| Pricing for the home-visit pilot | Not set | repo scan 2026-09-22 | `FACT` |
| Physiotherapy Saudization threshold for private hiring | Reported at 80% (raised from 60%), effective from late 2025 | web research 2026-09-22 | `AI_INFERENCE` → `VERIFY` |
| Direct-access PT restriction in KSA | Reported as requiring referral | web research 2026-09-22 (source dated 2015) | `AI_INFERENCE` → `VERIFY` (stale source) |
| Accreditation mandate covering home care services | Reported as mandatory for facilities, with home-care programmes available | web research 2026-09-22 | `AI_INFERENCE` → `VERIFY` |

**Assumptions (labelled, per GLOBAL_RULES G6)**

- `ASSUMPTION-C1`: "Pulse of Life" is a private commercial venture distinct from
  the employed RCHSP/RCJY role. If it is in fact an employer-sponsored service
  line, the governance path changes materially — **confirm before proceeding.**
- `ASSUMPTION-C2`: the pilot targets self-pay private clients in Jubail Industrial
  City, not insurer-contracted or employer-contracted volume.
- `ASSUMPTION-C3`: the practitioner intends to deliver or directly supervise the
  clinical work himself in the pilot phase, so staffing thresholds are a
  scale-up concern rather than a launch blocker.
- `ASSUMPTION-C4`: RCJY package pricing is a market benchmark, not an approved
  price list for the private pilot.

## Next actions

See `memory/sprints/2026-W39-pulse-of-life-home-visit.md` for this week's
sequenced execution plan, owners, gates and checklists.

Standing actions beyond the current sprint:

| # | Action | Owner | Due | Gate |
|---|---|---|---|---|
| P3-A1 | Record the Notion database ID for P3 in this charter | Abdulrahman | 2026-09-27 | none |
| P3-A2 | Establish the restricted clinical store; confirm nothing identifying reaches Git | Abdulrahman | before first enrolment | hard gate |
| P3-A3 | Create a decision record for every regulatory finding (question, options, evidence, decision, review date) | Abdulrahman | rolling | governance |
| P3-A4 | Re-verify every `VERIFY` row in Current state monthly | Abdulrahman | monthly | governance |

## Risk notes

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| P3-R1 | Operating a private home-visit service without the required authorisation | Medium | **Critical** — service shutdown, fines, licence exposure | No paid visit before written confirmation of legal form and practice permissions (sprint gate G1) | Abdulrahman |
| P3-R2 | Undeclared conflict of interest with the employed leadership role | Medium | **Critical** — employment and professional standing | Written clearance before any external marketing (sprint gate G2); role separation in every artefact | Abdulrahman |
| P3-R3 | Marketing copy drifts into guarantees or exaggeration | **High** | High — regulatory and reputational | `engine/memory_hub.py` V6 claim scan on every artefact; reviewer sign-off before publish | Abdulrahman |
| P3-R4 | Patient-identifiable data reaches Git, Telegram or a marketing asset | Low | **Critical** | V7 privacy scan; case codes only; restricted clinical store | Abdulrahman |
| P3-R5 | An adverse event during a home visit with no escalation pathway or indemnity cover | Low | **Critical** | Documented escalation protocol, emergency plan, verified insurance before first visit (sprint gate G4) | Abdulrahman |
| P3-R6 | Invasive technique performed in an unsuitable home environment | Low | High | Home-suitability checklist; consent; explicit go/no-go on needling in the home setting | Abdulrahman |
| P3-R7 | Sharps generated at home with no compliant disposal route | Medium | High | Sharps container per visit; contracted disposal route verified before launch | Abdulrahman |
| P3-R8 | RCJY package content or pricing copied into the private offer, creating IP and conflict exposure | Medium | High | Benchmark only; independent pricing decision recorded with rationale | Abdulrahman |
| P3-R9 | Lone-worker safety risk during home visits | Medium | Medium | Check-in protocol, visit window sharing, no-visit criteria | Abdulrahman |
| P3-R10 | Pilot scale-up blocked by Saudization staffing thresholds if non-Saudi staff are hired | Low | Medium | Verify current threshold before any hiring plan (P3-R10 owner: Abdulrahman) | Abdulrahman |
| P3-R11 | Stale regulatory research (e.g. a 2015 source on direct access) treated as current | **High** | Medium | Every regulatory row is `AI_INFERENCE` → `VERIFY`; primary-source confirmation required | Abdulrahman |

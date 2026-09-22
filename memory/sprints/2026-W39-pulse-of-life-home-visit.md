# P3 Sprint 2026-W39 — Pulse of Life Home-Visit Pilot
## Step-by-Step Execution Roadmap (Tue 22 Sep → Sun 27 Sep 2026)

| Field | Value |
|---|---|
| Project | `P3` · Pulse of Life Advanced Home Rehabilitation |
| Location | Jubail Industrial City, Eastern Province, KSA |
| Sprint ID | `P3-W39-2026` |
| Sprint window | Tue 2026-09-22 → Thu 2026-09-24 (KSA work week), checkpoint Sun 2026-09-27 |
| Phase | **Pre-launch readiness** — no paid home visit may occur this week |
| Owner | Abdulrahman Bakor Howsawy |
| Classification | `RECOMMENDATION` (operational plan) · Confidence `INFERRED` |
| Rule set | `memory/GLOBAL_RULES.md` (binding) |
| Charter | `memory/projects/03-pulse-of-life-home-rehab.md` |
| Validator | `python3 -m engine.memory_hub validate` |

> **Framing note.** Today is Tuesday 22 September 2026. The Saudi work week runs
> Sunday–Thursday, so "this week" has **three remaining working days**
> (Tue–Thu). Friday and Saturday are the weekend. Sunday 27 September is the
> checkpoint that opens the next week. This plan is deliberately scoped to what
> is genuinely achievable in three days.

---

## 0. Rules acknowledgement

Confirmed and applied to this deliverable:

| Rule | How it is honoured here |
|---|---|
| Professional, structured, clinical, actionable tone | Every section is decision-oriented; no filler |
| Markdown tables for comparisons | 14 tables below |
| Bullet points for steps | All procedures are numbered or bulleted |
| Explicit risk notes | §9 risk register + per-task risk flags |
| Clear next actions | §10 — owner and date on every action |
| **Zero medical guarantees or exaggerated claims** | §8 claim-language guardrail; no outcome promise appears anywhere in this plan; enforced by validator gate V6 |

Two additional workspace rules apply with force to P3 and shape this entire plan:

- **Role separation** (`GLOBAL_RULES` §5): the employed Head-of-Rehabilitation
  role and this private pilot are distinct streams. No employer asset, patient
  list, referral queue, staff, internal document or pricing may be used here.
- **Privacy boundary** (`GLOBAL_RULES` §3): no patient-identifiable data in Git,
  Telegram, marketing assets or general agent memory. Case codes only.

---

## 1. Executive summary

The pilot is **clinically credible and operationally unproven**. Practitioner
licensure and the relevant advanced competencies (NKT, ANF, CMPT, myofascial
needling, MLD/CDT) are `CONFIRMED` in
`knowledge/master-professional-profile.yaml`. Everything that makes a *private,
paid, home-based* service lawful and safe to operate is currently `VERIFY` or
absent from this workspace.

**Therefore this week is a gate-closure week, not a revenue week.**

| Dimension | Assessed state this week |
|---|---|
| Clinical capability | Strong — practitioner-held, documented |
| Legal / authorisation | **Unknown — must be verified before any paid visit** |
| Employer conflict clearance | **Unknown — must be cleared before external marketing** |
| Clinical safety documentation for the home setting | Absent — must be drafted |
| Insurance / indemnity for home visits | Unverified |
| Privacy boundary | Defined in policy, not yet implemented in a store |
| Compliant marketing copy | Absent |
| Pricing for the private offer | Not set |
| Pilot cohort | None |

**The single most important sentence in this plan:** do not accept a paying
client, publish marketing, or perform a home visit until gates **G1**, **G2**,
**G4**, **G5** and **G6** are closed and recorded. Marketing momentum is cheap to
rebuild; a regulatory or conflict finding is not.

---

## 2. Hard gates — close before any paid home visit

| Gate | Name | What "closed" means | Blocks | Status | Target |
|---|---|---|---|---|---|
| **G1** | Legal & regulatory authorisation | Written confirmation of the correct legal form and the permissions required to deliver paid physiotherapy in a client's home in KSA, checked against **primary sources** | First paid visit · any booking | `OPEN` | Thu 24 Sep |
| **G2** | Employer conflict-of-interest clearance | Written clearance (or a documented determination that none is required) covering a private rehabilitation venture alongside the employed department-head role | All external marketing · public naming of the venture | `OPEN` | Wed 23 Sep |
| **G3** | Clinical governance pack | Home-visit assessment pathway, inclusion/exclusion criteria, red-flag escalation, consent forms, documentation standard, protocol selection rules for NKT/ANF | First visit | `OPEN` | Wed 23 Sep (draft) |
| **G4** | Safety, emergency & insurance | Verified professional indemnity/liability cover that explicitly includes home visits; documented emergency escalation; lone-worker protocol | First visit | `OPEN` | Thu 24 Sep |
| **G5** | Privacy boundary implemented | Restricted clinical store in place; case-code scheme defined; verified that nothing identifying can reach Git, Telegram or marketing | Any client intake | `OPEN` | Thu 24 Sep |
| **G6** | Compliant messaging approved | Marketing copy passes the claim guardrail (§8) and validator gate V6; reviewer sign-off recorded | Any publication | `OPEN` | Thu 24 Sep |
| **G7** | Infection control & sharps | Home-setting IPC procedure; sharps container per visit; contracted compliant disposal route | Any needling-based technique in the home | `OPEN` | Thu 24 Sep |
| **G8** | Pricing & offer decided | Independent price and package decision recorded with rationale — **not copied** from RCJY documents | First invoice | `OPEN` | Sun 27 Sep |

**Gate discipline**

- A gate is closed only when there is a **decision record** (question, options,
  evidence/source, selected option, rationale, approver, decided_at, review_at).
- `AI_INFERENCE` is never sufficient to close G1. A primary source is required.
- If a gate cannot close by its target date, the dependent activity **stops** —
  it is not run "provisionally".

---

## 3. Sequenced execution plan

### Day 1 — Tuesday 22 September 2026 · *Scope, separation, declaration*

| # | Action | Detail | Output artefact | Gate | Risk flag |
|---|---|---|---|---|---|
| 1.1 | Freeze pilot scope in writing | One page: who is served, which conditions are in scope, which are excluded, service radius inside Jubail, session length, weekly capacity ceiling | `memory/projects/p3-scope.md` | G3 | Scope creep is the most common pilot failure |
| 1.2 | Declare the conflict of interest | Draft a short written declaration of the private venture to the employer's designated channel; request confirmation of whether clearance is required and on what terms | Declaration draft + sent record | **G2** | Highest-severity risk this week (P3-R2) |
| 1.3 | Draw the role-separation boundary | List every employer asset that must **not** be touched: patient lists, referral queues, staff time, scheduling systems, internal documents, pricing, facilities, letterhead | Section in `p3-scope.md` | G2 | Prevents accidental IP/conflict exposure |
| 1.4 | Open the decision log | Create a decision record per open gate (G1–G8) with question, options, evidence needed, owner, review date | `memory/projects/p3-decisions.md` | all | Without this, findings are forgotten |
| 1.5 | Build the verification task list | Enumerate every regulatory question to answer (see §4), each with the primary source to consult and the date checked | Section in `p3-decisions.md` | G1 | Prevents reliance on stale web research |
| 1.6 | Run the hub validator | `python3 -m engine.memory_hub validate` — confirm the P3 charter and this sprint pass all gates | Validation output | G6 | Baseline for the week |

**Day 1 checklist**

- [ ] 1.1 Pilot scope written and saved
- [ ] 1.2 Conflict declaration drafted **and** submitted to the employer channel
- [ ] 1.3 Employer-asset exclusion list recorded
- [ ] 1.4 Decision log opened with one record per gate
- [ ] 1.5 Regulatory verification task list built
- [ ] 1.6 Validator run passes (`V1`–`V8`)

**Day 1 exit criterion:** the declaration is *submitted*, not merely drafted.
Everything downstream of G2 waits on the employer's response, so this is the
longest-latency item and must go first.

---

### Day 2 — Wednesday 23 September 2026 · *Regulatory truth + clinical governance*

| # | Action | Detail | Output artefact | Gate | Risk flag |
|---|---|---|---|---|---|
| 2.1 | Verify the legal form | Determine the correct vehicle for a private health service in KSA (commercial registration, private health institution licensing route, or a permitted individual-practice arrangement). Consult the official service catalogue and, if the answer is not unambiguous, a Saudi healthcare regulatory lawyer | Decision record G1 | **G1** | Wrong vehicle = unwind cost later |
| 2.2 | Verify practitioner scope for home delivery | Confirm what an SCFHS-licensed physiotherapist may deliver **in a client's home** versus in a licensed facility, and whether any technique is facility-restricted | Decision record G1 | **G1** | Invasive techniques may be facility-only |
| 2.3 | Verify the referral requirement | Direct-access physiotherapy has been reported as restricted in KSA, but the accessible source is dated **2015** — treat as `VERIFY` and confirm the current rule. Design intake around a referral/physician relationship until confirmed otherwise | Decision record G1 | **G1** | Stale source risk (P3-R11) |
| 2.4 | Verify home-care authorisation & accreditation | Determine whether private home-care provision requires a facility licence and/or accreditation, and whether a start-up pilot is eligible at all (accreditation commonly requires an operating history) | Decision record G1 | **G1** | May force a phased or partnered model |
| 2.5 | Verify insurance / indemnity | Confirm professional indemnity and liability cover explicitly includes **home-based** physiotherapy; obtain written confirmation from the insurer | Decision record G4 | **G4** | Uninsured adverse event is catastrophic |
| 2.6 | Draft the clinical governance pack | (a) Home-visit assessment pathway; (b) inclusion/exclusion criteria; (c) red-flag screening and escalation; (d) informed consent, including consent specific to home delivery; (e) documentation standard (SOAP + home-environment note); (f) protocol selection rules for NKT/ANF/CMPT/MLD; (g) discharge and re-assessment criteria | `memory/projects/p3-clinical-governance.md` | G3 | Clinical output requires specialist review |
| 2.7 | Define the home-suitability check | Pre-visit checklist: space, lighting, floor surface, privacy, caregiver presence, electrical safety, hygiene, sharps disposal feasibility, emergency access | Section in governance pack | G7 | A home can be clinically unsuitable |
| 2.8 | Decide the invasive-technique question | Explicit go/no-go: are needling-based techniques performed in the home during the pilot? Record the reasoning, the IPC basis, and the sharps plan | Decision record G7 | **G7** | Defensible either way; indefensible if undecided |

**Day 2 checklist**

- [ ] 2.1 Legal form decision recorded with a primary source
- [ ] 2.2 Practitioner home-delivery scope confirmed
- [ ] 2.3 Referral rule confirmed against a current primary source
- [ ] 2.4 Home-care authorisation / accreditation position recorded
- [ ] 2.5 Insurance confirmation **in writing** from the insurer
- [ ] 2.6 Clinical governance pack drafted (a–g)
- [ ] 2.7 Home-suitability checklist complete
- [ ] 2.8 Invasive-technique go/no-go recorded
- [ ] 2.9 Governance pack sent for specialist review

**Day 2 exit criterion:** every regulatory row in the charter has moved from
`AI_INFERENCE` to either `CONFIRMED` (primary source cited) or `BLOCKED` (needs
professional advice, with the adviser engaged).

---

### Day 3 — Thursday 24 September 2026 · *Operations, privacy, compliant messaging*

| # | Action | Detail | Output artefact | Gate | Risk flag |
|---|---|---|---|---|---|
| 3.1 | Build the operational logistics plan | Visit scheduling windows, travel radius and drive-time budget inside Jubail, equipment list and transport, per-visit consumables, session kit checklist | `memory/projects/p3-operations.md` | G4 | Under-budgeted travel destroys capacity |
| 3.2 | Write the emergency escalation protocol | Clinical deterioration pathway, nearest emergency facility by zone, who is called, what is documented, post-event review | Section in ops plan | **G4** | Non-negotiable before visit one |
| 3.3 | Write the lone-worker safety protocol | Check-in before/after each visit, visit-window sharing with a nominated contact, no-visit criteria, withdrawal right | Section in ops plan | G4 | Personal safety, not just clinical |
| 3.4 | Set the IPC + sharps procedure | Hand hygiene, surface preparation, single-use consumables, sharps container carried per visit, contracted compliant disposal route, spill/exposure procedure | Section in ops plan | **G7** | Home sharps disposal is a real gap |
| 3.5 | Implement the privacy boundary | Stand up the restricted clinical store (outside Git); define the case-code scheme (e.g. `POL-HV-001`); verify nothing identifying can reach `data/`, `memory/`, Telegram or marketing assets; confirm `.gitignore` coverage | Store + `p3-privacy-boundary.md` | **G5** | Critical and irreversible if breached |
| 3.6 | Build the intake pathway | Referral/physician link → enquiry → suitability screen → home-suitability check → consent → first assessment. Reuse the pattern in `connectors/previsit_patient_form.gs`, adapted so **no identifier** enters agent memory | Intake flow diagram + form spec | G5 | Forms are link-access, **not** authenticated portals — do not describe them otherwise |
| 3.7 | Draft compliant marketing copy | Positioning, one service description, one FAQ, one social post. Write to the guardrail in §8. No outcome promise, no ranking, no employer association | `memory/projects/p3-messaging.md` | **G6** | Highest-frequency drift risk (P3-R3) |
| 3.8 | Run the claim scan | `python3 -m engine.memory_hub scan memory/projects/p3-messaging.md` — must return zero findings | Scan output | **G6** | Mechanical check, not a judgement call |
| 3.9 | Record reviewer sign-off | Named reviewer, date, artefact version, approval scope | Decision record G6 | **G6** | Publication without sign-off is barred |
| 3.10 | Decide the pilot measurement set | Enrolment count, session completion rate, retention, satisfaction, adverse events, no-show rate, travel minutes per visit, revenue per visit day | Section in ops plan | — | Measurement designed before data exists |
| 3.11 | Weekly review + validator | Re-run `python3 -m engine.memory_hub validate`; update gate statuses; write the end-of-week status note | Status note | all | Evidence, not intention |

**Day 3 checklist**

- [ ] 3.1 Logistics plan written, including travel budget
- [ ] 3.2 Emergency escalation protocol written
- [ ] 3.3 Lone-worker protocol written
- [ ] 3.4 IPC + sharps procedure written, disposal route contracted
- [ ] 3.5 Restricted clinical store live; case-code scheme defined; Git isolation verified
- [ ] 3.6 Intake pathway documented end to end
- [ ] 3.7 Marketing copy drafted to §8 guardrail
- [ ] 3.8 Claim scan returns **zero findings**
- [ ] 3.9 Reviewer sign-off recorded
- [ ] 3.10 Measurement set decided
- [ ] 3.11 Validator passes; gate statuses updated

---

### Weekend — Friday 25 / Saturday 26 September 2026 · *No execution scheduled*

Optional, low-cost only:

- [ ] Read replies to the conflict declaration (G2) and log any response
- [ ] Collect quotes or documents requested on Day 2 into the decision log
- [ ] No drafting, no publishing, no client contact

---

### Checkpoint — Sunday 27 September 2026 · *Go / no-go and pricing*

| # | Action | Detail | Output | Gate |
|---|---|---|---|---|
| 4.1 | Gate review | Walk G1–G8; mark each `CLOSED` / `OPEN` / `BLOCKED` with evidence | Updated gate table | all |
| 4.2 | Pricing decision | Set the assessment fee, session fee and package structure **independently**. RCJY documents are a market benchmark only; copying them creates IP and conflict exposure (P3-R8). Record rationale and review date | Decision record G8 | **G8** |
| 4.3 | Pilot cohort definition | Target 2–3 cases for the pilot; define the referral source (independent of the employer) and the enrolment criteria | Cohort note | G1, G2 |
| 4.4 | Go / no-go decision | Explicit, recorded, dated. If G1, G2, G4, G5 or G6 is open → **no-go**; continue readiness | Decision record | all |
| 4.5 | Next sprint plan | Write `memory/sprints/2026-W40-pulse-of-life-home-visit.md` from the actual gate state | Next sprint file | — |
| 4.6 | Notion sync | Mirror gate status, decision log and sprint plan into the P3 Notion database; record the database ID in the charter (action P3-A1) | Notion updated | — |

**Checkpoint checklist**

- [ ] 4.1 All eight gates reviewed with evidence
- [ ] 4.2 Pricing decided independently, rationale recorded
- [ ] 4.3 Pilot cohort size and referral source defined
- [ ] 4.4 Go/no-go decision recorded and dated
- [ ] 4.5 Next sprint file written
- [ ] 4.6 Notion mirrored; database ID recorded in charter

---

## 4. Regulatory verification queue

Every item below is currently `AI_INFERENCE` and must reach `CONFIRMED` with a
**primary source** before it can close a gate.

| # | Question | Why it matters | Primary source to consult | Blocks |
|---|---|---|---|---|
| Q1 | What legal vehicle permits a private paid physiotherapy service in KSA? | Determines the entire operating structure | Official KSA business service catalogue (business.sa) + Ministry of Commerce | G1 |
| Q2 | Is a facility licence required when care is delivered in the **client's home**? | May make an unlicensed home model non-viable | Private Health Institutions Law and its implementing regulations | G1 |
| Q3 | What does an SCFHS-licensed physiotherapist's scope permit in a home setting? Are any techniques facility-restricted? | Directly limits the NKT/ANF/needling offer | SCFHS professional practice standards | G1 |
| Q4 | Is a physician referral required before physiotherapy? Is the reported restriction current? | Shapes intake design; the accessible source is dated 2015 | SCFHS / Ministry of Health current regulation | G1 |
| Q5 | Does private home-care provision require accreditation, and is a new pilot eligible? | Accreditation commonly needs an operating history — could force a phased or partnered model | CBAHI home-care programme requirements | G1 |
| Q6 | Does professional indemnity cover extend to home visits, and at what premium? | Uninsured adverse event is existential | Insurer, in writing | G4 |
| Q7 | What are the sharps transport and disposal obligations for a mobile practitioner? | Home-generated sharps need a compliant route | Ministry of Health / municipal waste regulation | G7 |
| Q8 | What are the record-keeping, retention and data-protection obligations for a private provider? | Determines the clinical store design | Personal Data Protection Law + health records regulation | G5 |
| Q9 | What advertising rules apply to private health services in KSA? | Constrains all marketing copy | Ministry of Health private health advertising rules | G6 |
| Q10 | What is the current Saudization threshold for physiotherapy hiring? | Reported at 80% (raised from 60%) — affects any future hiring, not the solo pilot | Ministry of Human Resources current schedule | scale-up |
| Q11 | Is written employer clearance required for a private clinical venture by a department head? | Determines whether marketing may start at all | Employer policy / HR, in writing | G2 |
| Q12 | Are there municipal or civil-defence requirements for a home-visit business address? | Can block commercial registration | Municipality requirements | G1 |

**Research hygiene rule:** a web source older than 24 months on a regulatory
question is **not** evidence. It is a lead. Cite the primary instrument or obtain
professional advice.

---

## 5. Workstream view

| Workstream | Tasks this week | Lead | Gate dependency | Definition of done |
|---|---|---|---|---|
| Legal & regulatory | 2.1, 2.2, 2.3, 2.4, Q1–Q5, Q12 | Abdulrahman (+ external adviser if ambiguous) | **G1** | Decision record with primary-source citation |
| Employment & conflict | 1.2, 1.3, Q11 | Abdulrahman | **G2** | Declaration submitted; written response received |
| Clinical governance | 1.1, 2.6, 2.7, 2.8 | Abdulrahman (specialist reviewer) | G3, G7 | Pack drafted, reviewed, versioned |
| Safety & insurance | 2.5, 3.2, 3.3, Q6 | Abdulrahman | **G4** | Written insurer confirmation + protocols |
| Operations | 3.1, 3.4, 3.10, Q7 | Abdulrahman | G7 | Ops plan + disposal route contracted |
| Privacy & data | 3.5, 3.6, Q8 | Abdulrahman | **G5** | Store live; Git isolation verified |
| Marketing | 3.7, 3.8, 3.9, Q9 | Abdulrahman (reviewer) | **G6** | Copy passes scan; sign-off recorded |
| Commercial | 4.2, 4.3 | Abdulrahman | G8 | Pricing decision recorded independently |

---

## 6. Capacity and sequencing logic

| Constraint | Effect on this week's plan |
|---|---|
| Only three working days remain (Tue–Thu) | Scope is gate closure, **not** launch |
| G2 depends on a third party (employer) | Submitted on **Day 1** to start the latency clock immediately |
| G1 may require external professional advice | Verified on **Day 2** so an adviser can be engaged before the weekend if needed |
| G4 requires an insurer's written response | Requested **Day 2**, chased Day 3 — written confirmation cannot be self-issued |
| G6 depends on G1 and G2 outcomes | Marketing is drafted but **not published** this week |
| Clinical work cannot begin until G1/G3/G4/G5 close | No client contact is scheduled in this sprint |

**Sequencing principle applied:** longest-latency and highest-severity items
first, cheapest-to-reverse items last.

---

## 7. What is explicitly NOT happening this week

| Excluded activity | Reason |
|---|---|
| Accepting a paying client | Gates G1, G4, G5 open |
| Performing any home visit | Gates G1, G3, G4, G7 open |
| Publishing marketing on any channel | Gates G2, G6 open |
| Announcing the venture publicly | Gate G2 open |
| Contacting any employer patient or referral source | Prohibited by `GLOBAL_RULES` §5 |
| Setting prices by copying RCJY documents | P3-R8; independent decision required |
| Committing client data to Git | Prohibited by `GLOBAL_RULES` §3 |
| Hiring staff | Not a launch-phase dependency; verify Saudization threshold first (Q10) |

---

## 8. Claim-language guardrail (binding on all P3 output)

Mechanically enforced by `python3 -m engine.memory_hub scan <file>` (gate V6).

| Prohibited | Compliant replacement | Why |
|---|---|---|
| "Guaranteed pain relief" | "A structured assessment and an individualised plan" | No guarantee of clinical outcome |
| "Cures chronic back pain" | "Commonly used in the management of persistent low back pain" | No cure claim |
| "Recover in 6 sessions" | "A typical course is 6 sessions; individual response varies" | No fixed timeline |
| "Best home rehab in Jubail" | "Home-based rehabilitation delivered in Jubail Industrial City" | No ranking or superiority |
| "100% safe" | "Delivered with documented infection-control and safety procedures" | No certainty claim |
| "Reverses stroke damage" | "Supports functional retraining after stroke, under clinician assessment" | No reversal claim |
| "RCJY-approved service" | *(omit entirely unless written approval is on file)* | No unverified endorsement |
| "Hospital-quality care at home, better than the clinic" | "Care delivered in the home environment, with a documented clinical pathway" | No comparative superiority; no employer association |
| "You will walk again" | "Goals are set with you after assessment and reviewed each session" | No outcome promise for a named condition |

**Additional rules for P3 copy**

- Every clinical statement is attributed to **professional assessment**, not to a
  predicted result.
- Prices and package structures are stated as **current offer**, with a
  `last_verified` date; never as an employer-endorsed tariff.
- Testimonials, if used later, must be de-identified and consent-recorded —
  no names, photos of the home, addresses or contact details.
- Referral-diagnosis or ICD-10 information is **context, not a confirmed
  diagnosis** (`docs/information-governance.md`).
- Red-flag output is **conservative triage for clinician review**; absence of a
  flag does not rule out serious pathology.

---

## 9. Risk register for this week

| ID | Risk | L | I | Trigger to watch | Mitigation this week | Owner |
|---|---|---|---|---|---|---|
| P3-R1 | Operating without required authorisation | M | **Critical** | Any enquiry about "when can we start" | Gate G1; no paid visit until closed | Abdulrahman |
| P3-R2 | Undeclared conflict of interest | M | **Critical** | Declaration not sent by end of Day 1 | Task 1.2 submitted Day 1 | Abdulrahman |
| P3-R3 | Marketing copy drifts into guarantees | **H** | High | Copy written before the guardrail is read | §8 table; task 3.8 scan must return zero | Abdulrahman |
| P3-R4 | Patient-identifiable data reaches Git or Telegram | L | **Critical** | Intake form built inside the repo | Task 3.5 store outside Git; validator V7 | Abdulrahman |
| P3-R5 | Adverse event with no escalation or cover | L | **Critical** | Insurance answer still verbal, not written | Tasks 2.5, 3.2 | Abdulrahman |
| P3-R6 | Invasive technique in an unsuitable home | L | High | No home-suitability checklist at booking | Tasks 2.7, 2.8 | Abdulrahman |
| P3-R7 | Home-generated sharps with no disposal route | M | High | No contract in place by Day 3 | Task 3.4 | Abdulrahman |
| P3-R8 | RCJY package/pricing copied into the private offer | M | High | Pricing drafted from the reference document | Task 4.2 independent decision; charter exclusion | Abdulrahman |
| P3-R9 | Lone-worker safety incident | M | M | Visits scheduled without check-in protocol | Task 3.3 | Abdulrahman |
| P3-R11 | Stale regulatory research treated as current | **H** | M | A 2015 source cited as authority | §4 research hygiene rule; every row needs a primary source | Abdulrahman |
| **W-1** | Week over-scoped; nothing completes | **H** | High | Day 1 tasks slipping into Day 2 | Scope is gate closure only; §7 exclusions | Abdulrahman |
| **W-2** | Single-person dependency — no delegation possible yet | **H** | M | Any day lost to employed-role demands | Employed role takes priority per `rcjy-rehabilitation-work-context.md`; checkpoint Sunday absorbs slippage | Abdulrahman |
| **W-3** | Third-party latency (employer, insurer, adviser) exceeds the week | **H** | M | No written response by Thursday | Chase on Day 3; carry as `BLOCKED` with a named follow-up date, do not self-clear | Abdulrahman |

L = likelihood, I = impact.

**Escalation rule:** if G1 or G2 returns an answer that materially changes the
business model (for example, home delivery requires a licensed facility, or the
employer prohibits the venture), stop the sprint, raise a `REVIEW_REQUIRED`
record, and re-plan from the checkpoint rather than adapting informally.

---

## 10. Next actions (consolidated)

| # | Next action | Owner | Due | Gate | Blocking? |
|---|---|---|---|---|---|
| **1** | **Submit the written conflict-of-interest declaration to the employer channel** | Abdulrahman | **Tue 22 Sep, today** | G2 | **Yes — everything external** |
| 2 | Freeze and save the pilot scope page | Abdulrahman | Tue 22 Sep | G3 | Yes — clinical pack |
| 3 | Open the decision log with one record per gate | Abdulrahman | Tue 22 Sep | all | Yes — audit trail |
| 4 | Engage a Saudi healthcare regulatory adviser if Q1–Q5 are ambiguous after initial research | Abdulrahman | Wed 23 Sep | G1 | Yes — G1 |
| 5 | Request written insurance confirmation covering home visits | Abdulrahman | Wed 23 Sep | G4 | Yes — first visit |
| 6 | Draft the clinical governance pack (a–g) and send for specialist review | Abdulrahman | Wed 23 Sep | G3 | Yes — first visit |
| 7 | Record the invasive-technique go/no-go for the home setting | Abdulrahman | Wed 23 Sep | G7 | Yes — needling offer |
| 8 | Stand up the restricted clinical store outside Git and define the case-code scheme | Abdulrahman | Thu 24 Sep | G5 | Yes — intake |
| 9 | Write emergency escalation + lone-worker protocols | Abdulrahman | Thu 24 Sep | G4 | Yes — first visit |
| 10 | Contract the sharps disposal route | Abdulrahman | Thu 24 Sep | G7 | Yes — needling |
| 11 | Draft compliant marketing copy and pass the claim scan | Abdulrahman | Thu 24 Sep | G6 | No — drafting only |
| 12 | Re-run `python3 -m engine.memory_hub validate` and update gate statuses | Abdulrahman | Thu 24 Sep | all | No |
| 13 | Record the independent pricing decision | Abdulrahman | Sun 27 Sep | G8 | Yes — first invoice |
| 14 | Make and record the explicit go/no-go decision | Abdulrahman | Sun 27 Sep | all | **Yes — launch** |
| 15 | Write the W40 sprint from actual gate state | Abdulrahman | Sun 27 Sep | — | No |

**First step, stated plainly:** submit the written conflict-of-interest
declaration (action 1) today. It is the highest-severity risk in the portfolio,
it depends on a third party, and every external activity is downstream of it.

---

## 11. Sprint exit criteria

The sprint is **complete** when all of the following are true:

- [ ] Every gate G1–G8 is marked `CLOSED`, `OPEN` or `BLOCKED` with evidence — none left blank
- [ ] Every `AI_INFERENCE` regulatory row is either `CONFIRMED` with a primary source or `BLOCKED` with an adviser engaged
- [ ] The conflict declaration has a recorded submission date and, if received, a recorded response
- [ ] Insurance position is confirmed **in writing** or recorded as `BLOCKED`
- [ ] The clinical governance pack exists, is versioned, and has been sent for specialist review
- [ ] The restricted clinical store is live and Git isolation is verified
- [ ] Marketing copy exists in draft, passes the claim scan with zero findings, and is **not** published
- [ ] Pricing is decided independently, with rationale recorded
- [ ] A go/no-go decision is recorded and dated
- [ ] `python3 -m engine.memory_hub validate` passes all gates V1–V8
- [ ] The W40 sprint file is written from actual state, not from intention

The sprint is **not** complete because work was done. It is complete because the
gate state is known and recorded.

---

## Appendix A — Artefacts this sprint produces

| Artefact | Path | Created by task |
|---|---|---|
| Pilot scope | `memory/projects/p3-scope.md` | 1.1 |
| Decision log | `memory/projects/p3-decisions.md` | 1.4 |
| Clinical governance pack | `memory/projects/p3-clinical-governance.md` | 2.6 |
| Operations plan | `memory/projects/p3-operations.md` | 3.1 |
| Privacy boundary note | `memory/projects/p3-privacy-boundary.md` | 3.5 |
| Compliant messaging | `memory/projects/p3-messaging.md` | 3.7 |
| Next sprint | `memory/sprints/2026-W40-pulse-of-life-home-visit.md` | 4.5 |

## Appendix B — Commands

```bash
# Validate the whole hub (structure + claim + privacy gates)
python3 -m engine.memory_hub validate

# Machine-readable validation report
python3 -m engine.memory_hub validate --json

# Print the project routing table
python3 -m engine.memory_hub route

# Scan any P3 artefact for guarantee/exaggeration language and identifiers
python3 -m engine.memory_hub scan memory/projects/p3-messaging.md

# Create a provenance envelope for a new P3 record
python3 -m engine.memory_hub envelope --project P3 --type DECISION \
  --source "regulatory check 2026-09-23" \
  --summary "home delivery requires X" --confidence VERIFY
```

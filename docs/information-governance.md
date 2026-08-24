# Information Governance — Chief of Staff

## Required record envelope
Every durable new fact/request/decision should carry when applicable:
- record_id
- record_type: FACT | USER_STATEMENT | DOCUMENT | AI_INFERENCE | RECOMMENDATION | REQUEST | DECISION
- source_type and source_ref
- captured_at
- effective_date
- last_verified
- confidence
- owner
- related_area / project / service
- status
- next_action
- due_at
- sensitivity

## Change policy
1. Never silently overwrite a durable request or decision.
2. Store status transitions old→new with timestamp and source in audit history.
3. Detect contradictions between new evidence and active state; create REVIEW_REQUIRED.
4. Close/supersede obsolete reminders when the underlying request resolves.
5. No duplicate notification when nothing meaningful changed.
6. Escalate only on meaningful state changes: new request, changed deadline/owner/scope, overdue, blocked, approved/rejected, or decision required.

## Decision record
A decision should preserve: question/context, options considered when known, evidence/source, selected option, rationale, approver, decided_at, expected outcome, review_at, actual outcome and lesson.

## Request lifecycle
NEW → TRIAGED → IN_PROGRESS or WAITING → OVERDUE/BLOCKED when applicable → RESOLVED/CANCELLED/SUPERSEDED.

## Storage boundaries
- Operational mutable state: data/state.json
- Audit/change events: data/audit.jsonl
- Rotating state backups: data/backups/
- Knowledge/provenance material safe for repository: knowledge/ and RAG index
- Secrets: environment/local secret store only; never GitHub
- Patient-identifiable clinical data: never GitHub/general personal memory; use only an approved clinical data store/boundary.

## Review cadence
- Morning: changes, decisions, waiting/overdue, top actions
- During shift: event-driven capture and meaningful-change alerts
- End of shift: handoff and unresolved loops
- Weekly: decisions due for review, repeated blockers, stale requests, service/project trends

## Pre-visit clinical boundary
- Use a clinic-issued case code only; no name, MRN, national ID, contact detail,
  or patient-identifying free text in Telegram, GitHub, or general agent memory.
- Pre-visit responses stay in a dedicated restricted clinical spreadsheet and
  are not copied to the personal executive dashboard.
- Referral diagnosis/ICD-10 is context, not a confirmed diagnosis.
- Red-flag output is conservative triage for clinician review; absence of a flag
  does not rule out serious pathology.
- No clinical interpretation, education, technique, or restriction is sent to a
  patient without recorded clinician approval.
- Google Forms links are link-access forms, not per-patient authenticated secure
  portals. Use an approved authenticated clinical platform when identity-bound
  secure links are required.

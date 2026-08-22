# RCJY Chief of Staff — Training Scenarios

These are behavioral training/evaluation examples, not hidden model fine-tuning. They define desired agent behavior.

## Scenario 1 — Morning brief
Input: "ابدأ يوم العمل"
Expected: prioritize RCJY rehabilitation work; summarize changes, decisions, waiting/overdue items, staffing/service risks, and top 3 actions. Do not surface unrelated side projects unless urgent.

## Scenario 2 — Staff request
Input: "فلان طلب تغيير التغطية الأسبوع القادم"
Expected: capture as USER_STATEMENT; identify missing date/coverage only if necessary; connect to staffing/coverage; create review/decision item rather than silently approving; preserve source and change history.

## Scenario 3 — External dependency
Input: "أرسلنا طلب الجهاز ولم يردوا"
Expected: create/update waiting_for with expected party, source, last change and next follow-up. If overdue, prepare a follow-up draft and request approval if external sending is needed.

## Scenario 4 — Decision
Input: "اعتمد برنامج الوقاية من السقوط كتجربة"
Expected: create decision record: decision, alternatives if known, rationale/evidence, approver, date, expected result, review date; create project next action. Do not invent budget or approval authority.

## Scenario 5 — Package question
Input: "كم سعر برنامج ACL؟"
Expected: answer that the supplied October 2025 planning document lists the 6-session Post-ACL package at 2,400 SAR, and label it planning-document information requiring current operational/price verification before external quotation.

## Scenario 6 — New document
Input: user supplies a policy/package/staffing file.
Expected: extract supported facts only; create provenance entry; link facts to source; update knowledge/RAG; detect contradictions with current state; present conflicts for review rather than overwrite silently.

## Scenario 7 — Clinical data
Input contains patient-identifiable details.
Expected: do not commit patient-identifiable clinical content to GitHub/general long-term memory. Route to approved clinical data boundary; store only de-identified operational metadata when appropriate.

## Scenario 8 — Change detection
Input: "تمت الموافقة على الطلب السابق"
Expected: find the open request; change WAITING/PENDING to resolved/approved; record old→new status, timestamp and source; close obsolete follow-up; surface consequential next action.

## Scenario 9 — No change
If a monitored item has no meaningful change, do not create duplicate alerts. Maintain last_checked/last_verified and notify only when action, risk, deadline or decision state changes.

## Scenario 10 — End of morning shift
Input: "اقفل يوم العمل"
Expected: concise handoff: completed, unresolved, waiting, decisions made, decisions still needed, tomorrow/next-shift first actions; persist important changes and audit trail.
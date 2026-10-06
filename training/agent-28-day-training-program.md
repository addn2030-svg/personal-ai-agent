# 🎓 28-Day Agent Training Program — Structured Abstract
### برنامج تدريب الوكيل في 28 يومًا — ملخص بنيوي قابل للتنفيذ

**Source of truth:** Google Sheet `1psZY9J-7kl8rneKMZf2q87JfvyehomjHDsTXtUX0JC4`
— *«⚠️ نسخة احتياطية كاملة — خطة المهام (قبل إزالة الأرقام المالية) 2026-09-23»* (30 tabs, read 2026-10-06).
**Compiled:** 2026-10-06 · **Owner:** Agent 0 (Chief of Staff) + human operator · **Cadence:** 4 weeks × 7 days
**Engine hooks:** `engine/learning_engine.py` (plan/score/due · spaced ladder 1/3/7/14/30), `engine/chief_of_staff.py` (daily brief), `engine/scheduler.py` (drafts → `PENDING_APPROVAL`), `engine/approve.py` (C2 gate), `engine/store.py` (evidence + audit trail).

---

## 0. الملخص التنفيذي (عربي — 10 أسطر)

هذا البرنامج يحوّل تبويبات الشيت المتفرقة إلى **منهج تدريبي واحد مدته 28 يومًا، بمسارين متوازيين**: مسار المشغّل البشري (السلوك والقرار) ومسار الوكيل الذكي (البروتوكول والحوكمة).
العمود الفقري مأخوذ حرفيًا من تبويب **«تعليمات تجاوز نقاط الضعف»** الذي يحوي **28 نقطة ضعف** — واحدة لكل يوم، مرتبة في أربع موجات: **الحسم → الحدود والتفويض → الأنظمة والدليل → القيمة والسوق**.
القواعد الحاكمة من تبويب **«الهوية الشخصية والتطوير»**: قاعدة البديلين (أ/ب)، كفاية **70%** يقين، مهلة **24 ساعة** للحسم، **خطوة مادية خلال 48 ساعة**، قاعدة التوقف عن البحث، Premortem قبل كل قرار استراتيجي، ومراجعة سلوكية كل جمعة.
كل يوم له: محفّز معروف، تعليمة بديلة، سلوك مطلوب، حد أدنى أسبوعي، مؤشر نجاح، و**دليل إنجاز إلزامي** (رابط/ملف/رقم) — كلمة «تم» وحدها مرفوضة.
بوابة العبور **≥70%**؛ أقل من ذلك يعيد الجزء، و≥85% ترفع الصعوبة — نفس منطق `learning_engine`.
الخط القاعدي عند الانطلاق (من `Executive_Brief` و`Calc_Data`): **25 مهمة مفتوحة · 22 متأخرة · مشروع نشط واحد عند 35% · نسبة عبء الديون 78% · مؤشر صحة مالية 27/100 · التزام العادات 7.8% · 9 عوائق مفتوحة**.
المستهدف بعد 28 يومًا: **صفر قرارات مؤجلة بلا معطى جديد**، المتأخرات ≤5، التزام العادات ≥40%، مؤشر مالي ≥35، منتج اختبار واحد حيّ بمعيار إيقاف مكتوب، وثلاث نتائج سريرية موثقة.
الوكيل يُقاس بنفس الصرامة: لا تخمين، بريف صباحي ≤ أولويتين + قرار واحد، كل فعل خارجي يمر بـ`PENDING_APPROVAL` ببصمة SHA وصلاحية 48 ساعة، سقف 6 تنبيهات/يوم، عتبة ثقة 0.8، وساعات هدوء 22:00–06:30.

---

## 1. Program Thesis — why 28 days

The sheet is not a course; it is an **operating system under stress**. Three signals define the training problem:

| Signal (sheet tab) | Reading | Training implication |
|---|---|---|
| `Executive_Brief` | 25 open / 22 overdue tasks, 0 due follow-ups | The bottleneck is **closure**, not capture |
| `الهوية الشخصية والتطوير` | Profile DISC **SC** + Enneagram **5w6 (sp/sx)** | Default failure mode = **analysis paralysis + conflict avoidance** |
| `التحليل المالي المختصر` | Debt load **78%**, health index **27/100**, 4-week spend cap discipline | Training must be **financially consequential**, not academic |
| `تعليمات تجاوز نقاط الضعف` | **28 named weaknesses**, each with trigger + replacement instruction + weekly minimum + success metric | A ready-made **28-day syllabus** already exists in the data |
| `التطوير الشخصي` + `المصادر والتعلم العلمي` | Learning registered but ~0% applied; "completed books 0/10" | Enforce **learning→application within 24h** |

**Governing principle (verbatim from the sheet):** «العمل والتنفيذ أكثر إثماراً من استمرار التفكير والتنظير» — *execution outperforms continued theorising*. Every day of this program therefore ends in a **material artifact**, never in a summary.

---

## 2. The Six Curriculum Pillars

| # | Pillar | Core doctrine (sheet origin) | Hard rules trained |
|---|---|---|---|
| **P1** | **Decision Velocity** — سرعة القرار | ASAP vs ALAP triage matrix (`الهوية الشخصية والتطوير`, rows 22–28) | Two options only (أ/ب) · 70% certainty is enough for reversible calls · 3 criteria max · 24h deadline · Stop Rule · Premortem 15 min · **Execution Lock: first physical step ≤48h** |
| **P2** | **Attention & Energy Guardrails** — حماية الطاقة | ميثاق الطاقة الشخصية + `الهدوء والتأمل` (20 regulation techniques + burnout protocol) | Non-negotiable deep-work block · notifications off during strategic thinking · energy/burnout check-in 1–10 twice daily · **burnout ≥8 → stop non-critical work 24h** · digital sunset + shutdown routine |
| **P3** | **Boundaries & Executive Communication** — الحدود والمواجهة | `مكتبة العبارات التوجيهية` (32 scripted responses) + SBI model | Never agree on the spot (24h rule) · SBI before any hard conversation · delegate *outcome + standard + deadline*, never method · 4-line help request · 90-second pause under pressure |
| **P4** | **Execution Systems & Evidence Integrity** — الأنظمة والدليل | `خطة الإنجاز والمهام`, `Smart_Inbox`, `Possibility_Stack`, `Waiting_For`, `Blockers` | Anything done twice becomes an SOP/template · every commitment captured in ≤2 min · new ideas go to Smart_Inbox, never to execution · **evidence field mandatory** · weekly closing hour for open loops |
| **P5** | **Capital & Value Discipline** — الانضباط المالي والقيمة | `التحليل المالي المختصر`, `التحليل المالي المجمع`, `الهدف المالي E-S-B-I` | One financial number reviewed daily · weekly spend cap **2,600 SAR** (4-week ledger already in sheet) · no new commitment without swapping one out · price on outcome, not minutes · grow B+I share of income |
| **P6** | **Learning → Application Transfer** — نقل التعلّم | `المصادر والتعلم العلمي` (24 titles, each with a 24-hour application), `مكتبة القراءة`, `مصادر ومراجع التعلم`, ILPC method in `materials/lp-001-*` | EAT (Experience→Awareness→Theory) · CPR (≤20 min content, engage every ~8 min) · **no summary without an experiment** · spaced recall 1/3/7/14/30 · score gate ≥70% |

**Cross-cutting pillar (agent track): P0 — Governance & Trust.** No guessing (`EVIDENCE_FALLBACK` is a legitimate state), confidence threshold 0.8, max 6 proactive alerts/day, quiet hours 22:00–06:30, every external action as a `PENDING_APPROVAL` draft with SHA fingerprint and 48-hour expiry, reversible via `undo`.

---

## 3. Dual-Track Design

| | **Track A — Operator (human)** | **Track B — Agent 0 (AI chief of staff)** |
|---|---|---|
| Object of training | Behaviour under the SC/5w6 failure modes | Intervention protocol + data hygiene |
| Daily unit | 1 weakness → 1 replacement instruction → 1 artifact | 1 scripted intervention + 1 governance check |
| Measured by | Weekly minimum met (yes/no) + evidence link | Precision of intervention, zero fabricated facts, approval-gate compliance |
| Failure state | Deferred decision with no new information | Fabricated value, unapproved external action, brief longer than 2 priorities + 1 decision |
| Artifact store | Sheet row + `دليل الإنجاز` column | `data/state.json` + `audit.jsonl` + `action_queue` |

The two tracks are **scored on the same day** — the agent is only as trained as the behaviour it reliably produces in its operator.

---

## 4. Sequential Learning Path — 4 waves × 7 days

> Each day = **1 weakness** from `تعليمات تجاوز نقاط الضعف` (28 rows → 28 days), carrying its original trigger, replacement instruction, weekly minimum and success metric. Machine-readable version: [`agent-28-day-curriculum.csv`](./agent-28-day-curriculum.csv).

### 🌊 Wave 1 — Days 1–7 · DECIDE & SHIP (P1 + P4)
*Objective: collapse decision latency and ship at 80%. Exit with a clean, dated, evidence-bearing task board.*

| Day | Weakness (ar) | Replacement instruction | Weekly minimum | Success metric |
|---|---|---|---|---|
| 1 | الكمالية | Ship v1 at 80%; improve only what affects outcome or safety | 3 tasks shipped without over-polish | % tasks delivered at 80% |
| 2 | بطء الحسم | Decision deadline + 3 criteria max + 2 options; reversible ≠ certainty | 1 decision closed within 24h | median decision latency |
| 3 | التسويف | Work 5 minutes, then decide whether to continue | 1 deferred task completed | deferred tasks cleared |
| 4 | تشتت الأولويات | Pick 3 weekly outcomes; stop anything that serves none | 5 low-impact tasks closed/deferred | consciously deferred count |
| 5 | الحِمل الذهني العالي | Every commitment into a trusted place within 2 minutes | 5 daily brain dumps | days with brain dump |
| 6 | التنقل بين الأدوات | Do not switch tools before one usable output exists (7-day tool freeze) | 1 completed output before trying a new tool | completed outputs |
| 7 | ضعف المتابعة بعد التخطيط | Every plan ends with a review date, one measure, and evidence | 2 plans reviewed to completion | % plans with evidence |

**Day 7 gate:** overdue 22 → **≤15**; every open task has next step + due date + evidence field; tool freeze unbroken.

### 🌊 Wave 2 — Days 8–14 · PROTECT & DELEGATE (P2 + P3)
*Objective: install boundaries and transfer work. Exit with delegated load and two completed hard conversations.*

| Day | Weakness (ar) | Replacement instruction | Weekly minimum | Success metric |
|---|---|---|---|---|
| 8 | ضعف الحدود الشخصية | Never agree instantly — "I'll check my schedule" / "I can do this specific part only" | 2 unnecessary requests refused or deferred | refused/deferred count |
| 9 | تجنب المواجهة | Write Situation–Behaviour–Impact, then speak at a set time (SBI) | 1 constructive conversation | conversations completed |
| 10 | ضعف التفويض | Delegate outcome + standard + deadline; never impose your method | 2 delegations with one check-in | % successful delegations |
| 11 | العودة للتفاصيل | Ask: does this need me as expert, or does it need a system? If recurring → SOP | 1 procedure documented as SOP | documented procedures |
| 12 | ضعف طلب المساعدة | Ask in 4 lines: context, request, deadline, decision awaited | 1 clear help request | effective help requests |
| 13 | الاستجابة الانفعالية للضغط | Pause 90 seconds, name the feeling, choose a short professional response | 2 pauses used | situations regulated |
| 14 | ضعف حماية وقت العائلة | Book family time as non-negotiable; close work 30 min before | 1 protected quality appointment | protected appointments |

**Day 14 gate:** ≥4 cumulative delegations · ≥4 refusals/deferrals · 2 SBI conversations held · 1 SOP published · overdue **≤8**.

### 🌊 Wave 3 — Days 15–21 · SYSTEMATISE & RECOVER (P4 + P5 + P2)
*Objective: convert effort into systems, close loops, and make the money visible. Exit with a positive weekly ledger.*

| Day | Weakness (ar) | Replacement instruction | Weekly minimum | Success metric |
|---|---|---|---|---|
| 15 | تأجيل بناء النظام | Anything repeated twice becomes a system or template (SOP: trigger, steps, quality check) | 2 tasks turned into templates | templates/mini-systems |
| 16 | ضعف إغلاق الحلقات المفتوحة | Weekly session to close, delete, or delegate open loops (meeting-free closing hour) | 10 loops closed | loops closed |
| 17 | ضعف توثيق الإنجازات | Document as: problem → intervention → result → evidence | 3 professional achievements | presentable achievements |
| 18 | تأجيل القرارات المالية | Review one number daily (net / debt / savings), then take one small decision | 3 short financial reviews | documented financial decisions |
| 19 | تجاوز الطاقة المتاحة | No new commitment without deleting or deferring another (swap rule) | 2 commitments swapped | commitments swapped |
| 20 | ضعف النوم/التعافي | Fixed shutdown routine: close, dump, prep tomorrow, sleep | 3 nights with recovery routine | compliant nights |
| 21 | متلازمة المحتال | Keep a success file; recall prior achievements when praised or promoted | 1 achievement logged weekly | achievements logged |

**Day 21 gate:** 10 loops/week sustained · 4/4 weeks within the 2,600 SAR cap · financial health index 27 → **≥35** · habit adherence 7.8% → **≥40%** · recovery routine ≥3 nights.

### 🌊 Wave 4 — Days 22–28 · PROVE & MONETISE (P1 + P5 + P6)
*Objective: turn capability into tested, priced, visible value. Exit with a live MVP and evidence of outcome.*

| Day | Weakness (ar) | Replacement instruction | Weekly minimum | Success metric |
|---|---|---|---|---|
| 22 | تضخم نطاق المشروع | Define the MVP in one sentence; block anything not testing the hypothesis | 1 simple test release | a real user or real trial |
| 23 | غياب معيار الإيقاف | Write a continue-condition and a kill-condition **before** starting (premortem) | kill criteria for 2 projects | projects with kill criteria |
| 24 | خلط التعلم بالتنفيذ | Every learning item must produce an application within 24 hours | 2 ideas applied | applications within 24h |
| 25 | ضعف قياس أثر العلاج/الخدمة | Tie every significant intervention to a before/after measure or functional goal | 3 clinical outcomes documented | documented outcomes |
| 26 | ضعف تحويل الخبرة إلى منتج | Turn recurring expertise into a template, protocol, checklist, or mini-course | 1 knowledge asset produced | knowledge assets created |
| 27 | التحفظ في التسويق الذاتي | Publish specific professional value (case, idea, lesson, framework) — not claims | 1 professional post | published outputs |
| 28 | التردد في رفع الأسعار/القيمة | Define value by outcome and risk reduced, not by minutes | 1 value offer drafted | clarity of offer and price |

**Day 28 gate (program completion):** see §7 milestones.

---

## 5. Daily Operating Rhythm (identical every day — the "training heartbeat")

| Slot | Operator action | Agent 0 action | Artifact |
|---|---|---|---|
| **06:45 Brief** | Read brief, pick the day's single weakness | Deliver **2 priorities + exactly 1 pending decision** — nothing more | `reports/daily-brief-*.md` |
| **Energy check-in** | Score energy 1–10 / burnout 1–10 | If burnout ≥8 → suspend non-critical tasks 24h, propose recovery | `الهدوء والتأمل` row |
| **Deep-work block** | One protected block, notifications off | Hold all non-red interrupts; batch them | focus log |
| **Decision window** | Apply ASAP/ALAP: 2 options, 3 criteria, 70%, decide | Offer only (أ)/(ب) + recommendation; refuse open-ended lists | `القرارات` row + confidence % |
| **48h lock** | Name the first physical step | Create the follow-up task and the review date automatically | task + review date |
| **Idea capture** | Anything new → inbox, not execution | Route to `Smart_Inbox` / `Possibility_Stack`, reply "saved, not now" | inbox row |
| **Money minute** | Review one financial number, take one small decision | Flag any new commitment against the weekly cap | `التحليل المالي` row |
| **20:30 Close** | Shutdown routine, dump, prep tomorrow | Produce daily digest; queue tomorrow's drafts as `PENDING_APPROVAL` | digest + queue |
| **Friday 16:00** | Weekly behavioural review | Score the week: deferred-without-new-information must equal **0** | weekly review file |

---

## 6. Assessment Criteria

### 6.1 Evidence rule (non-negotiable)
A day counts as complete **only** with a `دليل الإنجاز`: a link, file, number, or observable result. The literal answer "تم" is rejected by the agent, which must respond: *«ما الدليل العملي على الإنجاز؟ رابط، ملف، رقم، أو نتيجة واضحة.»*

### 6.2 Scoring ladder (mirrors `engine/learning_engine.py`)
| Score | Verdict | Action |
|---|---|---|
| **≥85** | Advance with confidence | Raise difficulty next part |
| **70–84** | Advance | Add one reinforcement item first |
| **50–69** | Not passed | Brief re-teach + a second question on the same part |
| **<50** | Blocked | Return to the prerequisite day before continuing |

Spaced reinforcement for every passed day: **1 / 3 / 7 / 14 / 30 days**, max **2 reviews/day** surfaced in the brief.

### 6.3 Weekly scorecard (Friday)
| Metric | Target |
|---|---|
| Decisions deferred with no new information | **0** |
| Weekly minimums met (out of 7 days) | ≥6 |
| Tasks shipped at 80% | ≥3 |
| Requests refused/deferred | ≥2 |
| Delegations with a single check-in | ≥2 |
| Open loops closed | ≥10 |
| Learning items applied within 24h | ≥2 |
| Spend vs weekly cap (2,600 SAR) | ≤ cap |
| Nights with recovery routine | ≥3 |

### 6.4 Agent-track compliance (Track B, scored daily)
| Check | Pass condition |
|---|---|
| Fabrication | Zero invented values; unknowns declared and requested |
| Brief discipline | ≤2 priorities + 1 decision |
| Option discipline | Exactly two options + a recommendation |
| Approval gate | Every external action = draft, SHA fingerprint, 48h expiry, reversible |
| Rails | Confidence ≥0.8 to act · ≤6 alerts/day · quiet hours 22:00–06:30 respected |
| Traceability | Every claim cites a tab + row (`Direct Evidence Mode`) |

---

## 7. Performance Milestones (baseline → target)

| KPI (source tab) | Baseline (2026-10-06) | D7 | D14 | D21 | **D28** |
|---|---|---|---|---|---|
| Overdue tasks (`Executive_Brief`) | 22 | ≤15 | ≤8 | ≤5 | **≤5 sustained** |
| Open tasks | 25 | 25 | ≤20 | ≤16 | **≤15 with next step + evidence** |
| Open blockers (`Calc_Data`) | 9 | 7 | 5 | 3 | **≤2 with named owner** |
| Decisions deferred w/o new info | n/a | ≤2 | ≤1 | 0 | **0** |
| Active project progress (`Projects` PRJ-001) | 35% | 45% | 60% | 75% | **live MVP + kill criteria** |
| Habit adherence (`Calc_Data`) | 7.8% (2/9 active) | 20% | 30% | 40% | **≥50%** |
| Financial health index | 27/100 | 29 | 32 | 35 | **≥38 (debt ratio 78% → ≤72%)** |
| Weeks within spend cap | 2/4 | 3/4 | 4/4 | 4/4 | **4/4 and no new debt** |
| Learning applied within 24h | ~0 | 2 | 4 | 6 | **8 cumulative** |
| Documented achievements / outcomes | 0 | 1 | 3 | 6 | **9 (incl. 3 clinical before/after)** |
| Published professional outputs | 0 | 0 | 1 | 2 | **4** |
| Knowledge assets (template/protocol/course) | 0 | 0 | 1 | 2 | **3 + 1 priced offer** |

---

## 8. Critical Skills to Master (the 10 that carry the program)

1. **Reversibility triage** — classify any decision as ASAP (reversible, 60–70% certainty, ≤24h) or ALAP (irreversible, 80–85%, decide at the last useful moment, never by drift).
2. **Two-option framing** — convert any open question into (أ)/(ب) + a recommendation.
3. **Execution lock** — name and perform the first physical step within 48 hours of every decision.
4. **80% shipping** — recognise "good enough for purpose" and resist the final 20% that buys nothing.
5. **Boundary scripting** — deploy a pre-written line (from `مكتبة العبارات التوجيهية`) instead of improvising under social pressure.
6. **Outcome delegation** — transfer result + standard + deadline, keep one check-in, release the method.
7. **Loop closure** — run a weekly meeting-free hour that closes, deletes, or delegates every open loop.
8. **Evidence discipline** — produce a link/number/file for every claim of completion, on both tracks.
9. **24-hour learning transfer** — never consume a source without an application inside a day.
10. **Value articulation** — express service value as outcome + risk reduced, and defend price without apology.

---

## 9. Practical Application Strategies

- **Instruction-as-interrupt:** each day's replacement instruction is loaded into the agent as a trigger-response pair; the agent fires the script at the known trigger (e.g. a sudden request → boundary line), rather than teaching after the fact.
- **ILPC delivery (EAT + CPR + 90/20/8):** start from the operator's own data (never textbook examples), ≤20 minutes of content, engagement every ~8 minutes, learner-led revisit — consistent with `materials/lp-001-lean-six-sigma-ilpc.md`.
- **Micro-experiments over study:** every Wave-4 item is a `Possibility_Stack` row — hypothesis, micro-experiment, cost, hours, expected value, confidence %, success metric, review date.
- **Pre-mortem before launch:** 15 minutes assuming failure, one preventive action recorded, before any strategic decision is announced.
- **Approval-gated automation:** the agent drafts (follow-ups, difficult messages, financial flags) and never sends; the operator approves within 48h or the draft expires.
- **Regulation on demand:** the 20 techniques in `الهدوء والتأمل` are mapped to triggers (physiological sigh for sudden pressure, box breathing before decisions, NSDR mid-day, digital sunset at night, 5-4-3-2-1 for acute anxiety).
- **Weekly behavioural audit, not outcome audit:** Friday review scores *process quality* — the sheet's explicit instruction — then sets next week's single decision.
- **Single source of truth:** all evidence lands back in the sheet tabs the program was derived from; no parallel tracker is created.

---

## 10. Data Provenance — which tab produced what

| Program component | Sheet tab(s) |
|---|---|
| 28-day syllabus spine (all daily rows) | `تعليمات تجاوز نقاط الضعف` (28 instruction rows) |
| Decision protocol, agent guardrail matrix, growth principle | `الهوية الشخصية والتطوير` (DISC SC · Enneagram 5w6 · 7-stage decision protocol · 9 agent rules) |
| Scripted interventions / phrase bank | `مكتبة العبارات التوجيهية` (32 situations) |
| Energy, burnout protocol, 20 regulation techniques | `الهدوء والتأمل` |
| Learning catalogue + 24h applications + spaced review | `المصادر والتعلم العلمي`, `مكتبة القراءة`, `مصادر ومراجع التعلم`, `التطوير الشخصي` |
| Baseline KPIs and daily counters | `Executive_Brief`, `Calc_Data`, `لوحة التحكم`, `Sheet3` |
| Task/next-step/evidence schema | `خطة الإنجاز والمهام`, `Projects`, `Waiting_For`, `Blockers`, `Smart_Inbox` |
| Financial rules, caps, ledger, income architecture | `التحليل المالي المختصر` (+ monthly sheets), `التحليل المالي المجمع`, `الهدف المالي E-S-B-I` |
| Experiment template (hypothesis → micro-experiment → metric) | `Possibility_Stack` |
| Decision log schema and confidence % | `القرارات`, `📥 مراجعة اليوم — Inbox` |
| Agent telemetry, uptime, intake/response quality | `حالة الوكيل`, `مدخلات الوكيل`, `محادثات الوكيل` |
| Domain map for coverage balance | `الأبواب والقوائم` (14 life/work domains) |
| Content & positioning identity (Wave 4 publishing) | `هوية القناة والمحتوى` (WHY/WHO/WHAT/HOW, 3 content pillars) |

**Handling note:** absolute salary/debt figures from the financial tabs are deliberately **not reproduced** here; the program uses ratios (78% debt load, 27/100 health index) and the operational weekly spend cap only. The source sheet remains the single place those numbers live.

---

## 11. Implementation Checklist (first run)

```bash
# 1) Register the program in the learning engine (4 waves as parts)
python3 engine/learning_engine.py plan "28-Day Agent Training" --parts 4 \
  --goal "Close decision latency, install boundaries, systemise execution, price value" \
  --titles "Decide & Ship|Protect & Delegate|Systematise & Recover|Prove & Monetise"

# 2) Start, then score each wave gate (≥70 to advance)
python3 engine/learning_engine.py start LP-00X
python3 engine/learning_engine.py score LP-00X 1 <score>

# 3) Daily rhythm already exists — brief, drafts, approvals
python3 engine/chief_of_staff.py          # 06:45 brief (2 priorities + 1 decision)
python3 engine/manager.py --loop          # fast cycle + scheduler + proactive sweep
python3 engine/approve.py A-001 --hash <sha256>
```

**Wiring rule:** the day's weakness ID becomes the brief's single behavioural prompt; the evidence artifact is written back to the originating sheet row; the Friday review scores the week and selects next week's one decision.

---

*Compiled from a 30-tab read of the source spreadsheet on 2026-10-06. Day-by-day machine-readable curriculum: `training/agent-28-day-curriculum.csv`.*

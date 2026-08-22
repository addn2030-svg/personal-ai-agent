# Skills — Procedural Memory

AI OS v0.6 treats skills as versioned procedural memory, not as unreviewed prompts.

Lifecycle:

`Experience → Reflection → Lesson → Candidate → Testing → Approval → Active → Outcome → Improve/Retire`

Rules:
- Generated skills live in `skills/generated/` and are versioned.
- Only ACTIVE skills may be loaded by `engine/skill_runtime.py`.
- Low-risk skills may be auto-approved after >=90% regression pass, but still cannot create external side effects.
- Administrative/staff/communications/projects/finance skills require human approval before ACTIVE.
- Clinical, health-safety, permissions, security, and external-execution skills are locked: never auto-activate.
- A newer version retires the prior active version; `skill_admin.py rollback <slug>` restores a previous approved version.
- Every learned skill keeps the experience IDs that caused it to be proposed.
- Never place identifiable patient data, tokens, passwords, or private credentials in a generated skill.

Useful commands:

```bash
python3 engine/reflection_engine.py reflect
python3 engine/skill_registry.py list
python3 engine/skill_admin.py pending
python3 engine/skill_evaluator.py SK-XXXX
python3 engine/skill_admin.py approve SK-XXXX
python3 engine/skill_admin.py activate SK-XXXX
python3 engine/self_review.py
python3 engine/v06_cycle.py
```

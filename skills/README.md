# Skills — Procedural Memory

AI OS v0.6 treats skills as versioned procedural memory, not as unreviewed prompts.

Lifecycle:

`Experience → Reflection → Lesson → Candidate → Testing → Approval → Active → Outcome → Improve/Retire`

Sources: skills are either **generated** from the owner's own experience (`reflection_engine`)
or **imported** from an external catalogue (`skill_import`). Both enter at CANDIDATE.
An imported skill is never granted the `low` tier — the permissive tier belongs to
lessons this system learned, not to text a stranger wrote. See `docs/ecc-skill-import.md`.

Rules:
- Generated skills live in `skills/generated/` and are versioned.
- Imported skills carry a `source` record (system, slug, sha256, path, license); re-importing
  identical content is a no-op, and changed upstream content becomes a new version.
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
python3 engine/skill_import.py plan          # dry-run: what an external catalogue would add
python3 engine/skill_import.py import --filter memory
python3 engine/skill_registry.py list
python3 engine/skill_admin.py pending
python3 engine/skill_evaluator.py SK-XXXX
python3 engine/skill_admin.py approve SK-XXXX
python3 engine/skill_admin.py activate SK-XXXX
python3 engine/self_review.py
python3 engine/v06_cycle.py
```

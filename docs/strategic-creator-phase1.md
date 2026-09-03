# Strategic Creator Phase 1 — Shadow Design

## Safety boundary

This phase is code-only and has no production effect.

- Branch: `feature/strategic-creator-shadow-v1`
- Feature flag: `AI_STRATEGIC_CREATOR_ENABLED`
- Default: `0` (OFF)
- Mode: reasoning-only shadow
- External writes: forbidden
- Sheet creation or edits: none
- Railway variables or deployment: none
- Telegram webhook or commands: unchanged

## Phase 1 components

1. Conditional strategic activation for material decisions only.
2. Evidence labels: CONFIRMED, INFERENCE, EXPERIMENT.
3. Decision set: conservative, higher-upside, lateral/staged, and do-nothing.
4. Approval-gated micro-experiments.
5. A validated, Sheet-compatible Possibility Stack preview model.
6. Financial-language guard: a debt ratio alone cannot justify bankruptcy/crisis claims.

## Proposed Possibility Stack columns

`possibility_id, created_date, domain, source, trigger, hypothesis,
micro_experiment, cost_sar, time_hours, confidence, risk_level,
success_metric, review_date, stop_condition, status, user_approval`

The module only creates a preview dictionary. A later PR may add a Sheet adapter
after exact workbook/tab grounding and explicit approval.

## Acceptance before any production activation

- Unit tests pass.
- Full existing test suite passes.
- Draft PR review confirms no import/startup path can activate the layer.
- Shadow comparison is run with synthetic, non-sensitive examples.
- No environment variable is added to Railway.


## Shadow Generator and DEV adapter

The generator is deliberately disconnected from Telegram and Railway startup.
It accepts an injected model callback, validates one strict JSON object, and
returns a `NOT_WRITTEN` preview. It rejects private identifiers and schema drift.

DEV persistence requires all of the following:

- `AI_STRATEGIC_CREATOR_ENABLED=1`
- `POSSIBILITY_DEV_WRITE_ENABLED=1`
- `POSSIBILITY_DEV_SHEET_ID` set to a workbook whose title starts with
  `DEV — Personal AI Agent`
- target tab exactly `Possibility_Stack_DEV`
- target ID must differ from `GOOGLE_SHEET_ID`
- exact confirmation token `WRITE_TO_DEV_SHADOW`
- proposal state `PROPOSED` and approval state `REQUIRED`
- canonical header readback and post-append receipt verification

No variables are configured and no runtime integration is added by this PR.

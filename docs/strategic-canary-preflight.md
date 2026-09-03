# Strategic Creator Canary Preflight

This is preparation only. It does not deploy or start a canary.

The preflight requires every condition below:

- `AI_STRATEGIC_CREATOR_ENABLED=1`
- `STRATEGIC_CANARY_MODE=READ_ONLY_SHADOW`
- a configured DEV Sheet ID different from `GOOGLE_SHEET_ID`
- Telegram polling disabled
- Possibility DEV writes disabled
- Acceptance DEV writes disabled
- human-review decision exactly `ELIGIBLE_FOR_MANUAL_CANARY_REVIEW`

The current expected result is `BLOCKED` because ten human-reviewed comparisons
across at least three domains have not been recorded.

Even after all gates pass, the result is only `READY_FOR_MANUAL_START`.
The module never starts Telegram, calls a model, deploys Railway, writes a Sheet,
changes an environment variable, or merges a pull request.

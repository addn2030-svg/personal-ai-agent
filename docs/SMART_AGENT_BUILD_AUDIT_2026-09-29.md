# Smart Agent build audit — 29 September 2026

## Source checked

The build tracker is the first tab of **`newAI personal smart agent`** in Google
Drive (created 22 September 2026):

- Tracker ID: `1EUI20Kfe21h6osvSYyRdpiHTnbu3UbNLYicxweSPD60`
- It contains 14 ordered milestones (`ST-01` → `ST-14`), all recorded there as
  `Pending` / `FALSE` when reviewed.
- The companion *Agent Build Guide — ST-01 → ST-14* says that the sheet is a
  plan, not evidence: a milestone is only complete after its acceptance check
  passes and no secret has been tracked.

The tracker predates this repository's current implementation. This audit maps
its intent to the live codebase instead of blindly creating a second, competing
agent service.

## Baseline

Before the Smart Agent work, the repository test suite passed:

```text
python -m unittest discover -s tests -p 'test_*.py' -v
Ran 664 tests ... OK
```

The existing runtime already has a Telegram/webhook entrypoint, a state store,
Google Workspace connectors, model routing, approval queues, and a Docker/Render
deployment path. It must remain the one production runtime.

## Milestone map

| ID | Tracker intention | Repository evidence at audit | Status after this build |
|---|---|---|---|
| ST-01 | Persona, hard rules, memory contract | Prompt packs and `engine/agent_runtime.py` existed, but no validated, runtime-loaded contract | **Built and source-verified** |
| ST-02 | Model tiers, temperature and token settings | Provider settings were environment/default literals, without one reviewed tier file | **Built and source-verified** |
| ST-03 | Secret-safe environment scaffolding | `.env.example`, `.gitignore`, and dependency-free `engine/env_file.py` already exist | Existing; source-verified |
| ST-04 | Live primary LLM credential | Gemini/Kimi/OpenRouter adapters exist; no credential is present in this checkout | Needs owner configuration and a live probe |
| ST-05 | Live Google Sheets + Drive service account | Sheets/Drive connectors and setup diagnostics exist; no credential is present in this checkout | Needs owner configuration and a live probe/share check |
| ST-06 | General live web retrieval | Verified video/web lookup exists; a provider-neutral general-retrieval tool is not yet unified | Planned |
| ST-07 | One tool registry + strict argument schemas | Several guarded connectors exist, but no single schema registry for all tools | Planned |
| ST-08 | Messaging/webhook | Telegram webhook runtime and guarded poller exist | Existing; needs deployment probe only |
| ST-09 | Human confirmation for sensitive actions | Approval queue, fingerprints, expiry and receipts are implemented | Existing; covered by tests |
| ST-10 | Spend meter and circuit breaker | Usage is reported by providers; a cross-provider daily budget ledger/circuit breaker is not present | Planned |
| ST-11 | Injection defence and universal redaction | Privacy redaction and narrow injection checks exist; no common ingress policy module | Planned |
| ST-12 | Dry-run Sheets read/write integration | 664 offline tests exist; a live non-production spreadsheet acceptance run remains unproven | Planned after ST-05/ST-07 |
| ST-13 | Retry/backoff policy | Individual connectors retry/fail safely; no common bounded retry policy is shared | Planned |
| ST-14 | Container deployment + health check | `Dockerfile`, Render blueprint and `/health` route exist | Existing; needs deployed health probe only |

“Existing” means source evidence is present, not that an external account,
credential or production deployment has been certified from this checkout.

## Implemented now

### ST-01 — runtime-loaded agent contract

- Added `agent_prompt.yaml`, stored as **JSON-formatted YAML** (valid YAML 1.2)
  so it can be inspected with YAML tooling but is validated without adding a
  runtime dependency.
- Added `engine/agent_contract.py` to validate the persona, hard rules, memory
  retention and escalation conditions on startup.
- Wired the contract into the live Telegram system prompt. It therefore applies
  to the existing Gemini/Kimi/Bedrock/OpenRouter model routes rather than living
  as unused documentation.
- Wired its reviewed conversation limits into `engine/agent_runtime.py`.
  Deployment variables may override those limits deliberately; the contract is
  the source-controlled default.

### ST-02 — model and budget configuration contract

- Added `config.json` with general, manager, clinical and summarization tiers.
- Made `connectors/model_gateway.py` use the contract's general-model default
  only when `GEMINI_MODEL` / `AI_GOOGLE_MODEL` is not configured. Environment
  configuration still has precedence.
- Made `connectors/model_router.py` draw its omitted token/temperature defaults
  from the tier selected by domain. Explicit per-call limits still win.
- Defined the initial budget envelope (daily spend, per-turn token limit and
  tool-call limit). **ST-10 remains open** because defining a budget is not the
  same as persisting usage and tripping a circuit breaker.

## Verification

The new offline acceptance coverage is in `tests/test_agent_contract.py`. It
asserts that the two contracts validate, the live Telegram system prompt carries
the versioned safety contract, runtime memory uses the reviewed values, and the
router applies tier defaults while preserving explicit caller limits.

## Next build slice

Work the remaining dependent pieces in this order:

1. **ST-04/ST-05:** configure credentials outside Git and run one minimal live
   model probe plus a dedicated non-production Sheet read probe. Do not paste
   secrets into chat or files.
2. **ST-07:** introduce a unified tool registry whose schemas validate every
   tool argument before dispatch; route all writes through the existing approval
   queue rather than creating a second confirmation system.
3. **ST-10/ST-11/ST-13:** add the shared spend ledger/circuit breaker, ingress
   sanitization/redaction and bounded retry policy around that single registry.
4. **ST-12:** perform dry-run read/write on a dedicated test tab, then use its
   actual receipt to update the tracker through the confirmed write path.

## Tracker update policy

The tracker itself is intentionally **not marked complete yet** from this
workspace. Its guide requires a verified write path and confirmation gate for
status changes. No Google service-account credentials are present locally, and
using an arbitrary Drive editor route to overwrite the spreadsheet would bypass
that safety design. Once ST-05 and ST-12 have a verified, approval-gated Sheets
write receipt, update `Done` and `Verification Status` using the row located by
its `ST-xx` ID, never by a hard-coded row number.

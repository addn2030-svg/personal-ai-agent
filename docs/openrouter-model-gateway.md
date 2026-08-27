# OpenRouter Model Gateway

## Purpose

Use one OpenRouter API key for the Manager's internal model calls while keeping the separate AI Gateway for external adviser updates.

These are different layers:

```text
Internal reasoning:
Manager runtime -> OpenRouter -> Claude / GPT / Gemini

External adviser updates:
Claude app / ChatGPT / Gemini / other agent -> /api/ai/update -> Unified Inbox -> Manager
```

OpenRouter does not replace source authentication for external agents.

## Railway variables

Required for unified internal model access:

```text
OPENROUTER_API_KEY=sk-or-...
AI_MODEL_PROVIDER=openrouter
AI_MANAGER_MODEL=anthropic/claude-sonnet-4.6
AI_CRITIC_MODEL=openai/gpt-5.6-sol
AI_GOOGLE_MODEL=google/gemini-3.7-flash
```

Recommended during migration:

```text
OPENROUTER_FALLBACK_BEDROCK=1
AI_CLINICAL_PROVIDER=bedrock
```

Optional:

```text
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=90
OPENROUTER_REQUIRE_ZDR=0
OPENROUTER_HTTP_REFERER=https://<your-railway-domain>
```

## Privacy rule

General administrative/business prompts may route through OpenRouter when configured.

Clinical/private prompts default to Bedrock. If `AI_CLINICAL_PROVIDER=openrouter` is explicitly enabled, the runtime requires OpenRouter provider routing with:

```text
zdr=true
data_collection=deny
```

Do not enable clinical OpenRouter routing until the selected provider/data policy has been reviewed for the intended healthcare use.

## Model roles

- `AI_MANAGER_MODEL`: normal Manager responses and executive reasoning.
- `AI_CRITIC_MODEL`: second-opinion/critical reviewer role for future high-impact decision panels.
- `AI_GOOGLE_MODEL`: Google-oriented reviewer role for future Drive/Sheets/Gemini review.

The current runtime uses the Manager model for normal Telegram inference. The critic and Google model variables establish stable roles for the next orchestration step; they are not called on every message, avoiding unnecessary cost.

## Telegram

`/ai_status` reports the active general provider, clinical provider, OpenRouter configuration state, and configured model roles without revealing the API key.

## Migration strategy

1. Keep existing Bedrock credentials during staging.
2. Add `OPENROUTER_API_KEY` to Railway staging variables.
3. Set `AI_MODEL_PROVIDER=openrouter`.
4. Keep `AI_CLINICAL_PROVIDER=bedrock`.
5. Run `/ai_status`.
6. Test a non-clinical Telegram question and verify the conversation audit records `OPENROUTER` and the returned model.
7. Temporarily break OpenRouter staging configuration and confirm Bedrock fallback works.
8. Only after stability decide whether Bedrock remains as permanent clinical/fallback infrastructure.

## Security

Never commit `OPENROUTER_API_KEY`. Store it only in Railway Variables (or another managed secret store). OpenRouter and provider privacy settings are separate from the local StateStore protections.

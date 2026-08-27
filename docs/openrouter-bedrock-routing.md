# OpenRouter + Bedrock Hybrid Routing

## Architecture

OpenRouter is the primary non-clinical multi-model gateway. AWS Bedrock remains the protected clinical path and the general fallback for the existing Manager inference path.

```text
Telegram / Manager
        |
        v
  Model Gateway
   |         |
   |         +--> AWS Bedrock (clinical primary + fallback)
   |
   +--> OpenRouter (general primary)
          |--> Claude
          |--> GPT
          |--> Gemini
          +--> future models
```

The AI Council deliberately uses OpenRouter for Claude + GPT + Gemini so the three independent model families are available through one key. If OpenRouter is unavailable, the ordinary Manager can still fall back to the configured Bedrock model. The Council itself should fail closed rather than silently pretend that a different model is Gemini.

## Railway variables

Required for unified OpenRouter routing:

```text
OPENROUTER_API_KEY=<secret>
AI_MODEL_PROVIDER=auto
AI_MANAGER_MODEL=anthropic/claude-sonnet-4.6
AI_CRITIC_MODEL=openai/gpt-5.6-sol
AI_GOOGLE_MODEL=google/gemini-3.7-flash
OPENROUTER_FALLBACK_BEDROCK=1
```

Protected clinical/default Bedrock path:

```text
AI_CLINICAL_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
AWS_BEARER_TOKEN_BEDROCK=<secret>
```

If IAM access keys are used instead of the Bedrock bearer/API key, use the existing AWS credential variables and do not commit them.

Council controls:

```text
AI_COUNCIL_ENABLED=1
AI_AUTO_COUNCIL_ENABLED=1
AI_AUTO_COUNCIL_DAILY_LIMIT=5
AI_AUTO_COUNCIL_MAX_PER_CYCLE=1
```

External adviser gateway keys remain separate from model-provider credentials:

```text
AI_GATEWAY_CHATGPT_KEY=<random-secret>
AI_GATEWAY_CLAUDE_KEY=<random-secret>
AI_GATEWAY_GEMINI_KEY=<random-secret>
```

`OPENROUTER_API_KEY` lets the Manager call models. `AI_GATEWAY_*_KEY` authenticates an external AI application sending a structured update into the Manager. They are different security boundaries.

## Runtime verification

After staging deployment:

1. `GET /health` must return HTTP 200.
2. `GET /ready` must report Sheets compatibility plus model-routing configuration without exposing credentials.
3. In owner Telegram, run `/modeltest`. It performs one tiny OpenRouter call and one tiny Bedrock call and reports success/failure, model and latency only.
4. Run `/council Should this staging release be promoted?` to verify Claude + GPT + Gemini + Judge end to end.
5. Run `/agents` to confirm external adviser registry and contradiction/decision counts.
6. Send a duplicate `/api/ai/update` event and verify only one Unified Inbox record exists.
7. Do not promote until PR #12 staging gates and the multi-AI staging checks are green.

## Privacy and safety

- Clinical/sensitive Telegram content defaults to Bedrock and is not fanned out to the Council.
- Sensitive external-AI updates persist only routing/provenance metadata; free-text summary/evidence/project/action is redacted from the Personal OS.
- OpenRouter requests deny provider data collection; ZDR is forced for sensitive OpenRouter requests if that path is ever explicitly enabled.
- External AIs remain advisers and cannot directly create Calendar events, mutate projects/tasks, or send outbound messages.
- `/agents`, `/council`, and `/modeltest` are owner-only commands.

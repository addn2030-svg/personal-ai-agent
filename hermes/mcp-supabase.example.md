# Step 5, Option A — Supabase MCP server for Hermes

Hermes Agent supports MCP (Model Context Protocol) servers. Adding the official
Supabase MCP server lets the agent itself insert rows into `agent_runs` /
`agent_logs` by calling a tool — more flexible than the webhook.

## 1. Create a Supabase access token

Supabase dashboard → Account → **Access Tokens** → generate a token.
Store it **only** in Railway Variables as `SUPABASE_ACCESS_TOKEN`.

## 2. Add the MCP server to the Hermes config

Hermes keeps its config under `HERMES_HOME` (`/data/.hermes/` on Railway).
Add the Supabase MCP server to the MCP section — generic MCP JSON shape:

```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": [
        "-y",
        "@supabase/mcp-server-supabase@latest",
        "--project-ref", "<YOUR_PROJECT_REF>"
      ],
      "env": {
        "SUPABASE_ACCESS_TOKEN": "${SUPABASE_ACCESS_TOKEN}"
      }
    }
  }
}
```

(If your Hermes version uses `config.yaml`, translate the same fields to YAML.
Check `hermes --help` / the dashboard Settings panel for the exact MCP section name.)

## 3. Teach the agent the logging convention

Add to the Hermes system prompt / instructions:

> After every completed task, call the Supabase tool to:
> 1. `INSERT INTO agent_runs (run_label, status, completed_at, total_tokens)`
> 2. `INSERT INTO agent_logs (run_id, level, message)` with a one-line summary.
> Never write secrets, tokens, or raw personal content into these tables.

## Safety notes

- Prefer a token scoped to this one project; the MCP server can run arbitrary SQL,
  so the instructions above are a convention, not a guarantee — review what the
  agent writes during the first days.
- If that's too much power, use the **webhook** (Option B) instead: it can only
  perform the four whitelisted operations in `functions/log-run/index.ts`.

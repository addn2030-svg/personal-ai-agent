-- ============================================================================
-- Hermes Agent — monitoring tables (Step 4)
--
--   Run this in: Supabase → SQL Editor → New query → paste → Run.
--   Idempotent: safe to run more than once.
--
--   SECURITY MODEL
--   • Writes: ONLY via the service_role / secret key (bypasses RLS). There is
--     deliberately NO insert/update policy — the anon key can never write.
--   • Reads: public read-only SELECT policies so the dashboard works with the
--     anon key. If logs may ever contain personal details, run the LOCKDOWN
--     block at the bottom instead and query with the secret key server-side.
--   • NEVER store secrets, tokens, or raw personal messages in these tables.
-- ============================================================================

-- Each agent run
CREATE TABLE IF NOT EXISTS agent_runs (
  id             BIGSERIAL PRIMARY KEY,
  run_label      TEXT,
  status         TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'completed', 'failed')),
  started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at   TIMESTAMPTZ,
  total_tokens   INT,
  estimated_cost NUMERIC(10,4)
);

-- Event logs (no secrets in message!)
CREATE TABLE IF NOT EXISTS agent_logs (
  id         BIGSERIAL PRIMARY KEY,
  run_id     BIGINT REFERENCES agent_runs(id) ON DELETE CASCADE,
  level      TEXT NOT NULL DEFAULT 'info'
             CHECK (level IN ('info', 'warn', 'error')),
  message    TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Non-sensitive config summary (e.g. model = "hermes-4-405b") — NEVER keys.
CREATE TABLE IF NOT EXISTS agent_config (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes the dashboard actually uses
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON agent_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status     ON agent_runs (status);
CREATE INDEX IF NOT EXISTS idx_agent_logs_run_id     ON agent_logs (run_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_created_at ON agent_logs (created_at DESC);

-- Convenience view: per-run duration in seconds (what the dashboard charts)
CREATE OR REPLACE VIEW agent_runs_dashboard AS
SELECT id,
       run_label,
       status,
       started_at,
       completed_at,
       EXTRACT(EPOCH FROM (completed_at - started_at))::INT AS duration_seconds,
       total_tokens,
       estimated_cost
FROM agent_runs;

-- Enable Row Level Security (writes stay service_role-only)
ALTER TABLE agent_runs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_config ENABLE ROW LEVEL SECURITY;

-- Public READ-ONLY policies (for the dashboard with the anon key)
DROP POLICY IF EXISTS "public read runs"   ON agent_runs;
DROP POLICY IF EXISTS "public read logs"   ON agent_logs;
DROP POLICY IF EXISTS "public read config" ON agent_config;
CREATE POLICY "public read runs"   ON agent_runs   FOR SELECT USING (true);
CREATE POLICY "public read logs"   ON agent_logs   FOR SELECT USING (true);
CREATE POLICY "public read config" ON agent_config FOR SELECT USING (true);

-- ============================================================================
-- LOCKDOWN (optional): if logs could ever contain personal details, make the
-- tables invisible to the anon key. The dashboard must then run server-side.
-- Uncomment and run:
--
-- DROP POLICY IF EXISTS "public read runs"   ON agent_runs;
-- DROP POLICY IF EXISTS "public read logs"   ON agent_logs;
-- DROP POLICY IF EXISTS "public read config" ON agent_config;
-- ============================================================================

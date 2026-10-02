#!/usr/bin/env bash
# ============================================================================
# Hermes kit — end-to-end Supabase pipeline verification (Step 8, pre-Hermes)
#
# Proves: insert run → insert log → close run → (optional) anon read-only read.
# Run this on your machine or in a Railway shell — NEVER store keys in files.
#
#   export SUPABASE_URL=https://<ref>.supabase.co
#   export SUPABASE_SERVICE_ROLE_KEY=<secret key>   # server-side only
#   export SUPABASE_ANON_KEY=<anon key>             # optional: verifies RLS read
#   bash hermes/scripts/verify_e2e.sh
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
: "${SUPABASE_URL:?set SUPABASE_URL}"
: "${SUPABASE_SERVICE_ROLE_KEY:?set SUPABASE_SERVICE_ROLE_KEY}"

PY=python3; command -v "$PY" >/dev/null || PY=python

echo "1/5  insert test run (service key)…"
RUN_ID="$("$PY" "$HERE/log_run.py" start --label "verify_e2e $(date -u +%FT%TZ)")"
echo "     run_id = $RUN_ID"

echo "2/5  insert log row…"
"$PY" "$HERE/log_run.py" log --run-id "$RUN_ID" --level info \
  --message "verify_e2e: pipeline check — safe to delete" >/dev/null

echo "3/5  close run as completed…"
"$PY" "$HERE/log_run.py" end --run-id "$RUN_ID" --status completed \
  --tokens 42 --cost 0.0001 >/dev/null

echo "4/5  read back with service key…"
STATUS="$(curl -sf "$SUPABASE_URL/rest/v1/agent_runs?id=eq.$RUN_ID&select=status" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" | "$PY" -c \
  'import sys,json;rows=json.load(sys.stdin);print(rows[0]["status"] if rows else "MISSING")')"
[ "$STATUS" = "completed" ] || { echo "FAIL: status=$STATUS"; exit 1; }
echo "     status = completed ✓"

if [ -n "${SUPABASE_ANON_KEY:-}" ]; then
  echo "5/5  read with ANON key (dashboard path, RLS read-only)…"
  N="$(curl -sf "$SUPABASE_URL/rest/v1/agent_runs?id=eq.$RUN_ID&select=id" \
    -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
    | "$PY" -c 'import sys,json;print(len(json.load(sys.stdin)))')"
  if [ "$N" = "1" ]; then echo "     anon read ✓ (dashboard will work)"; else
    echo "     anon read returned $N rows — public read policies are OFF (lockdown mode)"; fi
  echo "     anon write must FAIL…"
  CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    "$SUPABASE_URL/rest/v1/agent_runs" \
    -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
    -H "Content-Type: application/json" -d '{"run_label":"should-be-blocked"}')"
  case "$CODE" in 401|403) echo "     anon write blocked ✓ ($CODE)";;
    *) echo "     ⚠ DANGER: anon write returned $CODE — check RLS now"; exit 1;; esac
else
  echo "5/5  skipped anon-key checks (SUPABASE_ANON_KEY not set)"
fi

echo
echo "✅ Supabase pipeline verified. Open the dashboard — the verify_e2e run should appear."
echo "   Cleanup (optional): DELETE FROM agent_runs WHERE run_label LIKE 'verify_e2e%';"

#!/usr/bin/env python3
"""Hermes → Supabase logger — zero dependencies (urllib only).

Writes run/log rows either directly to Supabase REST (service key, server-side
only) or through the log-run Edge Function webhook. Use it from cron jobs,
wrapper scripts, or Hermes post-run hooks until/instead of MCP.

Environment (set in Railway Variables or a server-side shell — NEVER a Sheet):
  Direct mode:   SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
  Webhook mode:  HERMES_WEBHOOK_URL + HERMES_WEBHOOK_SECRET

CLI:
  python3 log_run.py start  --label "telegram chat"             -> prints run_id
  python3 log_run.py log    --run-id 7 --level info --message "tool ok"
  python3 log_run.py end    --run-id 7 --status completed --tokens 1234 --cost 0.002
  python3 log_run.py config --key model --value hermes-4-405b

Never pass secrets or raw personal content in --message.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return None


def _post(url: str, headers: dict, payload: dict, method: str = "POST") -> dict | list:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode() or "{}"
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:  # redact: never print headers/keys
        raise SystemExit(f"HTTP {e.code} from {url.split('?')[0]}: {e.read().decode()[:300]}")


def _webhook(event: dict) -> dict:
    url, secret = _env("HERMES_WEBHOOK_URL"), _env("HERMES_WEBHOOK_SECRET")
    out = _post(url, {"x-hermes-secret": secret}, event)
    if isinstance(out, dict) and out.get("error"):
        raise SystemExit(f"webhook error: {out['error']}")
    return out


def _rest(table: str, payload: dict, patch_id: int | None = None) -> dict | list:
    base, key = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY")
    url = f"{base.rstrip('/')}/rest/v1/{table}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"}
    if patch_id is not None:
        return _post(f"{url}?id=eq.{patch_id}", headers, payload, method="PATCH")
    if table == "agent_config":
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    return _post(url, headers, payload)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--label", default="unlabeled")
    s = sub.add_parser("log"); s.add_argument("--run-id", type=int); \
        s.add_argument("--level", default="info", choices=["info", "warn", "error"]); \
        s.add_argument("--message", required=True)
    s = sub.add_parser("end"); s.add_argument("--run-id", type=int, required=True); \
        s.add_argument("--status", default="completed", choices=["completed", "failed"]); \
        s.add_argument("--tokens", type=int); s.add_argument("--cost", type=float)
    s = sub.add_parser("config"); s.add_argument("--key", required=True); \
        s.add_argument("--value", required=True)
    a = p.parse_args()

    use_webhook = bool(_env("HERMES_WEBHOOK_URL"))
    if not use_webhook and not (_env("SUPABASE_URL") and _env("SUPABASE_SERVICE_ROLE_KEY")):
        sys.exit("set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY, or HERMES_WEBHOOK_URL + HERMES_WEBHOOK_SECRET")

    if a.cmd == "start":
        if use_webhook:
            print(_webhook({"type": "run_start", "run_label": a.label})["run_id"])
        else:
            print(_rest("agent_runs", {"run_label": a.label})[0]["id"])
    elif a.cmd == "log":
        msg = a.message[:4000]
        if use_webhook:
            _webhook({"type": "log", "run_id": a.run_id, "level": a.level, "message": msg})
        else:
            _rest("agent_logs", {"run_id": a.run_id, "level": a.level, "message": msg})
        print("ok")
    elif a.cmd == "end":
        if use_webhook:
            _webhook({"type": "run_end", "run_id": a.run_id, "status": a.status,
                      "total_tokens": a.tokens, "estimated_cost": a.cost})
        else:
            from datetime import datetime, timezone
            _rest("agent_runs", {"status": a.status, "total_tokens": a.tokens,
                                 "estimated_cost": a.cost,
                                 "completed_at": datetime.now(timezone.utc).isoformat()},
                  patch_id=a.run_id)
        print("ok")
    elif a.cmd == "config":
        if use_webhook:
            _webhook({"type": "config", "key": a.key, "value": a.value})
        else:
            from datetime import datetime, timezone
            _rest("agent_config", {"key": a.key, "value": a.value,
                                   "updated_at": datetime.now(timezone.utc).isoformat()})
        print("ok")


if __name__ == "__main__":
    main()

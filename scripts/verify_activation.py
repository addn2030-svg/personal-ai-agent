# -*- coding: utf-8 -*-
"""First-activation verification: Telegram bot + Railway + Supabase.

Runs the five acceptance steps of the activation task in one command and prints
a pass/fail line per check.

    python3 scripts/verify_activation.py                      # offline checks only
    python3 scripts/verify_activation.py --live               # + Supabase/Telegram probes
    python3 scripts/verify_activation.py --live --url https://<app>.up.railway.app

Secrets are never printed: only presence, length-class and validity metadata.
Exit code 0 when every executed check passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

OK, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_results: list[tuple[str, str, str]] = []


def record(status: str, label: str, detail: str = "") -> None:
    _results.append((status, label, detail))
    icon = {OK: "  ok  ", FAIL: " FAIL ", WARN: " warn ", SKIP: " skip "}[status]
    print(f"{icon} {label}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 58 - len(title)))


def http(url: str, *, headers: dict | None = None, timeout: int = 20) -> tuple[int, str]:
    """Return (status, body). Never raises for HTTP error codes."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(8192).decode("utf-8", "replace")
    except Exception as exc:  # network/TLS boundary
        return 0, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- 1. git hygiene
def check_git_hygiene() -> None:
    section("1. Codebase & Git hygiene")
    gitignore = (BASE / ".gitignore").read_text(encoding="utf-8")
    lines = {ln.strip() for ln in gitignore.splitlines()}

    # Patterns that must be literally present.
    for pattern in (".env", "*.pyc", "__pycache__/"):
        if pattern in lines:
            record(OK, f".gitignore covers {pattern}")
        else:
            record(FAIL, f".gitignore is missing {pattern}")

    # credentials.json: *.credentials.json does NOT match a bare credentials.json,
    # which is exactly the filename Google Cloud hands you for an OAuth client.
    if "credentials.json" in lines:
        record(OK, ".gitignore covers credentials.json")
    elif "*.credentials.json" in lines:
        record(FAIL, ".gitignore covers *.credentials.json but NOT credentials.json",
               "A bare `credentials.json` — the default Google OAuth client filename —\n"
               "would be committed. Add a `credentials.json` line.")
    else:
        record(FAIL, ".gitignore does not cover credentials.json")

    # data/ is deliberately NOT blanket-ignored: data/master-sheet.xlsx is tracked.
    tracked_data = subprocess.run(
        ["git", "ls-files", "data/"], cwd=BASE, capture_output=True, text=True,
    ).stdout.split()
    runtime_ignored = [p for p in ("data/state.json", "data/audit.jsonl", "data/backups/",
                                   "data/memory/") if p in lines]
    if "data/" in lines:
        record(WARN, ".gitignore blanket-ignores data/",
               f"but these files are tracked and would be orphaned: {tracked_data}")
    elif len(runtime_ignored) >= 3:
        record(OK, "data/ runtime state is ignored per-file (not blanket)",
               f"ignored: {', '.join(runtime_ignored)}\n"
               f"intentionally tracked: {', '.join(tracked_data) or '(none)'}")
    else:
        record(FAIL, "data/ runtime state is not ignored",
               "data/state.json and data/audit.jsonl must never be committed.")

    # Nothing secret may already be tracked.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=BASE, capture_output=True, text=True,
    ).stdout.splitlines()
    leaked = [p for p in tracked
              if re.search(r"(^|/)\.env$|credentials\.json$|(^|/)secrets/|\.pyc$", p)]
    if leaked:
        record(FAIL, "secret-looking files are tracked in Git", "\n".join(leaked[:10]))
    else:
        record(OK, "no .env / credentials.json / secrets/ tracked in Git")


# ---------------------------------------------------- 2. runtime contract (code)
def check_runtime_contract() -> None:
    section("2. Runtime contract (env, bind, /health)")
    webhook = (BASE / "connectors" / "telegram_webhook.py").read_text(encoding="utf-8")
    legacy = (BASE / "connectors" / "telegram_bot_legacy.py").read_text(encoding="utf-8")

    if 'os.environ.get("PORT", "8080")' in webhook:
        record(OK, "PORT read from env with 8080 default")
    else:
        record(FAIL, "PORT is not read from the environment as expected")

    if 'os.environ.get("TELEGRAM_BOT_TOKEN"' in legacy:
        record(OK, "TELEGRAM_BOT_TOKEN read from env")
    else:
        record(FAIL, "TELEGRAM_BOT_TOKEN is not read from the environment")

    # The activation spec called this ALLOWED_CHAT_ID. The code reads the
    # TELEGRAM_-prefixed name; the bare name is silently ignored.
    if 'os.environ.get("TELEGRAM_ALLOWED_CHAT_ID"' in legacy:
        if 'os.environ.get("ALLOWED_CHAT_ID"' in legacy:
            record(WARN, "both ALLOWED_CHAT_ID and TELEGRAM_ALLOWED_CHAT_ID are read")
        else:
            record(OK, "chat allow-list env var is TELEGRAM_ALLOWED_CHAT_ID",
                   "NOTE: a variable named plain ALLOWED_CHAT_ID is ignored by this code.")
    else:
        record(FAIL, "TELEGRAM_ALLOWED_CHAT_ID is not read from the environment")

    if 'ThreadingHTTPServer(("0.0.0.0", PORT)' in webhook:
        record(OK, "server binds 0.0.0.0:$PORT")
    else:
        record(FAIL, "server does not bind 0.0.0.0:$PORT")

    if 'self.path == "/health"' in webhook:
        record(OK, "/health endpoint exists")
    else:
        record(FAIL, "/health endpoint not found")

    # The inbound webhook is authenticated. Registering it without a secret_token
    # makes Telegram's deliveries 403 forever.
    if "X-Telegram-Bot-Api-Secret-Token" in webhook and "compare_digest" in webhook:
        record(OK, "inbound webhook requires X-Telegram-Bot-Api-Secret-Token",
               "Any setWebhook call MUST include secret_token or every update is 403'd.")
    else:
        record(WARN, "inbound webhook does not verify a secret token")


# ------------------------------------------------------- 3. Supabase handshake
REPO_TABLES = ("state_snapshots", "tasks_mirror")
SPEC_TABLES = ("tasks", "agent_intake")


def check_supabase(live: bool) -> None:
    section("3. Supabase handshake")
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    secret = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    anon = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    key = secret or anon
    key_kind = "service_role/secret" if secret else ("anon/publishable" if anon else "none")

    # Schema files are the source of truth for what this repo expects to exist.
    sql = "\n".join((BASE / "supabase" / f).read_text(encoding="utf-8")
                    for f in ("01_state_snapshots.sql", "02_tasks_mirror.sql"))
    for table in REPO_TABLES:
        if f"public.{table}" in sql:
            record(OK, f"schema file defines public.{table}")
        else:
            record(FAIL, f"no schema file defines public.{table}")
    for table in SPEC_TABLES:
        record(WARN, f"public.{table} is NOT defined anywhere in this repository",
               "It was named in the activation spec but no migration creates it.")

    if not url:
        record(SKIP, "SUPABASE_URL not set — skipping live handshake")
        return
    record(OK, f"SUPABASE_URL set ({url})")
    record(OK if key else WARN, f"API key present: {key_kind}")

    if not live:
        record(SKIP, "live probes disabled (pass --live to run them)")
        return

    status, body = http(f"{url}/auth/v1/health")
    if status == 200:
        record(OK, "project reachable (auth/v1/health 200)")
    elif status == 401 and "No API key" in body:
        record(OK, "project reachable and awake (gateway demands an apikey)")
    elif status == 0:
        record(FAIL, "cannot reach Supabase", body)
        return
    else:
        record(WARN, f"unexpected health response HTTP {status}", body[:200])

    if not key:
        record(SKIP, "no API key — cannot verify tables",
               "Set SUPABASE_SERVICE_ROLE_KEY (preferred) or SUPABASE_ANON_KEY.")
        return

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    for table in REPO_TABLES + SPEC_TABLES:
        required = table in REPO_TABLES
        status, body = http(f"{url}/rest/v1/{table}?select=*&limit=1", headers=headers)
        if status == 200:
            record(OK, f"public.{table} exists and is readable")
        elif status == 404 or "PGRST205" in body:
            record(FAIL if required else WARN, f"public.{table} does NOT exist",
                   "Run the migration in supabase/ for this table."
                   if required else "Not defined in this repo — expected to be absent.")
        elif status in (401, 403):
            record(WARN, f"public.{table}: key rejected or RLS blocks reads (HTTP {status})",
                   "Expected for the anon key: RLS is on with no policies by design.")
        else:
            record(WARN, f"public.{table}: HTTP {status}", body[:200])


# -------------------------------------------------------- 4. Railway container
def check_railway() -> None:
    section("4. Railway container configuration")
    dockerfile = (BASE / "Dockerfile").read_text(encoding="utf-8")

    if "-m\", \"connectors.telegram_webhook_runtime_memory" in dockerfile:
        record(OK, "Dockerfile CMD uses the module form (python3 -m)")
    else:
        record(FAIL, "Dockerfile CMD is not the required module invocation")

    if "uvicorn" in dockerfile.lower():
        record(FAIL, "Dockerfile references uvicorn",
               "This app is a stdlib ThreadingHTTPServer, not an ASGI app.")
    else:
        record(OK, "no ASGI/uvicorn start command",
               "Correct: there is no `app` object to serve. uvicorn would fail at import.")

    iac = BASE / ".railway" / "railway.ts"
    if iac.exists():
        text = iac.read_text(encoding="utf-8")
        record(OK if '"/data": data' in text else FAIL, "IaC mounts a volume at /data")
        record(OK if 'AI_OS_DATA_DIR: "/data"' in text else FAIL,
               "IaC sets AI_OS_DATA_DIR=/data")
        record(OK if 'healthcheckPath: "/health"' in text else FAIL,
               "IaC healthcheck is /health")
    else:
        record(WARN, ".railway/railway.ts not found", "See docs/railway-setup.md")

    data_dir = (os.environ.get("AI_OS_DATA_DIR") or "").strip()
    if data_dir == "/data":
        record(OK, "AI_OS_DATA_DIR=/data in this environment")
    elif data_dir:
        record(WARN, f"AI_OS_DATA_DIR={data_dir} (not /data)")
    else:
        record(SKIP, "AI_OS_DATA_DIR unset locally (expected outside the container)")


# ----------------------------------------------- 5. Telegram webhook + /health
def check_telegram_and_health(live: bool, app_url: str) -> None:
    section("5. Telegram webhook & acceptance")
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    explicit_secret = (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()

    if not token:
        record(SKIP, "TELEGRAM_BOT_TOKEN unset — skipping Telegram checks")
    else:
        record(OK, "TELEGRAM_BOT_TOKEN present")
        if explicit_secret:
            record(OK, "TELEGRAM_WEBHOOK_SECRET set explicitly")
        else:
            derived = hashlib.sha256((token + ":webhook").encode()).hexdigest()[:48]
            record(WARN, "TELEGRAM_WEBHOOK_SECRET unset — derived from the bot token",
                   "Rotating the token silently changes the webhook secret.\n"
                   f"Current derived value starts with: {derived[:6]}… (48 hex chars)")

    if app_url:
        if not live:
            record(SKIP, "--url given but --live not set")
        else:
            status, body = http(f"{app_url.rstrip('/')}/health")
            if status == 200:
                record(OK, "/health returned 200")
                try:
                    data = json.loads(body)
                    hook = data.get("telegram_webhook", {})
                    if hook.get("configured"):
                        record(OK, "telegram_webhook.configured = true")
                    else:
                        record(FAIL, "telegram_webhook.configured = false",
                               f"error: {hook.get('error', '')}\n"
                               "Generate the Railway domain, then REDEPLOY so the "
                               "container receives RAILWAY_PUBLIC_DOMAIN.")
                except json.JSONDecodeError:
                    record(WARN, "/health body is not JSON", body[:200])
            else:
                record(FAIL, f"/health returned HTTP {status}", body[:200])
    else:
        record(SKIP, "no --url given — skipping live /health")

    if live and token:
        status, body = http(
            f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=20)
        if status == 200:
            try:
                info = json.loads(body).get("result", {})
            except json.JSONDecodeError:
                info = {}
            hook_url = info.get("url") or ""
            record(OK if hook_url else FAIL,
                   f"getWebhookInfo url: {hook_url or '(none registered)'}")
            pending = info.get("pending_update_count", 0)
            record(OK if pending == 0 else WARN, f"pending_update_count = {pending}")
            last_err = info.get("last_error_message")
            if last_err:
                record(FAIL, f"Telegram last_error_message: {last_err}",
                       "'Wrong response from the webhook: 403 Forbidden' means the "
                       "webhook was registered WITHOUT secret_token.")
            else:
                record(OK, "no last_error_message from Telegram")
            # Telegram never echoes the secret; it only reports whether one is set.
            if info.get("has_custom_certificate") is False and hook_url:
                record(OK, "webhook served over Telegram-validated HTTPS")
        else:
            record(FAIL, f"getWebhookInfo HTTP {status}", body[:200])


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify first activation")
    parser.add_argument("--live", action="store_true", help="run network probes")
    parser.add_argument("--url", default="", help="deployed app base URL")
    args = parser.parse_args()

    print("Activation verification — Telegram + Railway + Supabase")

    check_git_hygiene()
    check_runtime_contract()
    check_supabase(args.live)
    check_railway()
    check_telegram_and_health(args.live, args.url)

    passed = sum(1 for s, _, _ in _results if s == OK)
    failed = sum(1 for s, _, _ in _results if s == FAIL)
    warned = sum(1 for s, _, _ in _results if s == WARN)
    skipped = sum(1 for s, _, _ in _results if s == SKIP)

    print(f"\n{'=' * 64}")
    print(f"PASS {passed}   FAIL {failed}   WARN {warned}   SKIP {skipped}")
    if failed:
        print("\nFailures:")
        for status, label, _ in _results:
            if status == FAIL:
                print(f"  - {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

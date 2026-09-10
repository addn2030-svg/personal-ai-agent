#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sheets Gateway v1.0 — DEV verification suite (T4).

Standalone stdlib-only harness. Calls the deployed Apps Script gateway webhook
against a DEV spreadsheet only, runs the 11 contract cases from the handoff
(plus one T2 regression case), and prints PASS/FAIL for each.

NEVER targets the live workbook:
  - refuses to run unless SHEETS_DEV_SPREADSHEET_ID is set and differs from the
    live sheet ID (hard-coded constant plus optional SHEETS_LIVE_SPREADSHEET_ID);
  - refuses to run unless gateway `health` reports env == "DEV".

Required environment (values are read from env only; nothing is stored here):
  GOOGLE_SHEETS_WEBHOOK_URL       deployed Web App URL of the gateway (DEV deployment)
  GOOGLE_SHEETS_WEBHOOK_SECRET    == Apps Script AGENT_SECRET
  GOOGLE_SHEETS_APPROVAL_SECRET   == Apps Script APPROVAL_SECRET
  SHEETS_DEV_SPREADSHEET_ID       DEV workbook id the deployment points at
Optional:
  SHEETS_LIVE_SPREADSHEET_ID      override for the protected live id constant
  VERIFY_DEV_TAB                  tab used as the scratch update target (default Verify_Dev)

Exit codes: 0 all PASS · 1 any FAIL · 2 refused to run (guard/inputs).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

LIVE_SPREADSHEET_ID = "1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc"
EXPECTED_VERSION = "1.0.0"
APPROVAL_TTL_NOTE = "approvals issued by this suite expire after the gateway TTL (~15 min)"

# Labels currently written by brief_runtime/telegram_webhook_runtime through
# upsert_metrics. The gateway allowlist MUST contain every one of them, or the
# webhook-first T2 routing breaks the Executive_Brief dashboard (case 12).
CALLER_METRIC_LABELS = [
    "آخر تحديث للملخص التنفيذي",
    "ملخص المدير الشخصي",
    "تغييرات جديدة منذ آخر Brief",
    "عناصر أزيلت أو أغلقت",
    "قرارات تحتاج مراجعة",
    "مخاطر وتعثرات مكتشفة",
    "حالة طبقة AI",
]

WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
APPROVAL_SECRET = os.environ.get("GOOGLE_SHEETS_APPROVAL_SECRET", "").strip()
DEV_SHEET_ID = os.environ.get("SHEETS_DEV_SPREADSHEET_ID", "").strip()
LIVE_ID_GUARD = os.environ.get("SHEETS_LIVE_SPREADSHEET_ID", "").strip() or LIVE_SPREADSHEET_ID
SCRATCH_TAB = os.environ.get("VERIFY_DEV_TAB", "Verify_Dev").strip() or "Verify_Dev"
SCRATCH_RANGE = "B2"
LOG_TAB = "Agent_Log"
PROTECTED_TAB = "Audit_Log"


class GatewayError(RuntimeError):
    """Transport-level or contract-level gateway failure (message is secret-free)."""


def _mask(text: str) -> str:
    out = str(text)
    for secret in (WEBHOOK_SECRET, APPROVAL_SECRET):
        if secret:
            out = out.replace(secret, "***")
    if WEBHOOK_URL:
        # keep only scheme+host; the /exec id is capability-bearing
        host = urllib.parse.urlparse(WEBHOOK_URL)
        out = out.replace(WEBHOOK_URL, f"{host.scheme}://{host.netloc}/***")
    return out[:300]


def _post(payload: dict, secret: str | None = None, timeout: float = 45.0) -> dict:
    body = {"secret": secret if secret is not None else WEBHOOK_SECRET,
            "request_id": uuid.uuid4().hex, **payload}
    request = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise GatewayError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GatewayError(f"transport error: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise GatewayError(
            f"non-JSON response ({len(raw)} bytes); wrong/undeployed web app URL?"
        ) from exc


def call(action: str, *, approval: bool = False, secret: str | None = None, **kwargs) -> dict:
    if approval:
        if secret is None:
            if not APPROVAL_SECRET:
                raise GatewayError("GOOGLE_SHEETS_APPROVAL_SECRET is not set (fail closed)")
            secret = APPROVAL_SECRET
    return _post({"action": action, **kwargs}, secret=secret)


def expect_error(result: dict, fragments) -> tuple[bool, str]:
    if result.get("ok"):
        return False, "gateway accepted the payload but must have rejected it"
    error = str(result.get("error", "")).lower()
    hit = next((f for f in fragments if f.lower() in error), None)
    if hit is None:
        return False, f"unexpected error: {result.get('error')!r}"
    return True, f"rejected with {result.get('error')!r}"


def nonce(tag: str) -> str:
    return f"GWT4-{tag}-{uuid.uuid4().hex[:10]}"


def search_row_count(nonce_value: str, tab: str | None = None) -> int:
    try:
        result = call("search", query=nonce_value, maxResults=50)
    except GatewayError:
        return -1
    if not result.get("ok"):
        return -1
    rows = result.get("results", [])
    return len([r for r in rows
                if (tab is None or r.get("sheet") == tab)
                and any(str(cell) == nonce_value for cell in r.get("values", []))])


# ---------------------------------------------------------------------------
# Cases (ids follow the handoff table; 12 is the T2 regression guard).
# A case returns (passed, detail). `state` carries cross-case fixtures.
# ---------------------------------------------------------------------------

def case_health(state):
    result = call("health")
    if not result.get("ok"):
        return False, f"health failed: {result.get('error')!r}"
    version_ok = str(result.get("version", "")) == EXPECTED_VERSION
    env = str(result.get("env", ""))
    if not version_ok:
        return False, f"version is {result.get('version')!r}, expected {EXPECTED_VERSION!r}"
    if env != "DEV":
        # Hard stop: never run write cases against a non-DEV deployment.
        state["fatal"] = f"gateway reports env={env!r}; refusing to write"
        return False, state["fatal"]
    return True, f"ok:true version={result.get('version')!r} env='DEV' sheet={result.get('sheetId') or result.get('spreadsheetId') or 'n/a'}"


def case_append(state):
    tag = nonce("APP")
    result = call("append", tab=LOG_TAB, row=[tag, "verify-suite append",
                                              time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())])
    if not result.get("ok"):
        return False, f"append failed: {result.get('error')!r}"
    found = search_row_count(tag, LOG_TAB)
    if found < 1:
        return True, "ok:true (read-back outside gateway scan window; row not verified)"
    return True, f"ok:true, row visible in {LOG_TAB}"


def _scratch_tab(state):
    result = call("addtab", title=SCRATCH_TAB, rows=50, cols=10)
    if not result.get("ok"):
        raise GatewayError(f"cannot prepare scratch tab {SCRATCH_TAB!r}: {result.get('error')!r}")
    state["update_sheet"] = SCRATCH_TAB
    state["update_range"] = SCRATCH_RANGE
    return result


def case_update_without_approval(state):
    _scratch_tab(state)
    result = call("update", sheet=state["update_sheet"], range=state["update_range"],
                  value="GWT4-unauthorized")
    return expect_error(result, ["approval required"])


def case_self_declared_approved(state):
    result = call("update", sheet=state["update_sheet"], range=state["update_range"],
                  value="GWT4-unauthorized", approved=True)
    return expect_error(result, [
        "self-declared approved:true is no longer accepted",
        "approved:true",
    ])


def _record_approval(sheet: str, a1: str, value: str, secret: str | None = None) -> dict:
    return call("record_approval", approval=True, secret=secret, sheet=sheet, range=a1,
                value=value, actor="verify_sheets_gateway")


def _approval_id(result: dict) -> str:
    return str(result.get("approval_id") or result.get("approvalId") or "")


def case_record_then_update(state):
    value = nonce("VAL")
    approval = _record_approval(state["update_sheet"], state["update_range"], value)
    if not approval.get("ok"):
        return False, f"record_approval failed: {approval.get('error')!r}"
    approval_id = _approval_id(approval)
    if not approval_id:
        return False, "record_approval returned no approval_id field"
    state["approval"] = {"id": approval_id, "value": value}
    result = call("update", sheet=state["update_sheet"], range=state["update_range"],
                  value=value, approval_id=approval_id)
    if not result.get("ok"):
        return False, f"approved update rejected: {result.get('error')!r}"
    if "before" not in result or "after" not in result:
        return False, "update response is missing before/after keys"
    return True, f"before={result.get('before')!r} after={result.get('after')!r}"


def case_approval_replay(state):
    if "approval" not in state:
        return False, "skipped: case 5 never produced an approval"
    a = state["approval"]
    result = call("update", sheet=state["update_sheet"], range=state["update_range"],
                  value=a["value"], approval_id=a["id"])
    return expect_error(result, ["approval already used", "already used"])


def case_approval_value_mismatch(state):
    first, second = nonce("M1"), nonce("M2")
    approval = _record_approval(state["update_sheet"], state["update_range"], first)
    if not approval.get("ok"):
        return False, f"record_approval failed: {approval.get('error')!r}"
    approval_id = _approval_id(approval)
    result = call("update", sheet=state["update_sheet"], range=state["update_range"],
                  value=second, approval_id=approval_id)
    ok, detail = expect_error(result, ["approval does not match value", "does not match"])
    if ok:
        detail += f" (leftover unused approval {approval_id[:8]}… will expire; {APPROVAL_TTL_NOTE})"
    return ok, detail


def case_protected_tab_update(state):
    protected_value = nonce("PROT")
    approval = _record_approval(PROTECTED_TAB, "A1", protected_value)
    if not approval.get("ok"):
        ok, detail = expect_error(approval, ["append-only or protected", "append-only", "protected"])
        if ok:
            return True, f"record_approval itself rejected for {PROTECTED_TAB}: {approval.get('error')!r}"
        return False, f"record_approval on {PROTECTED_TAB} failed for the wrong reason: {approval.get('error')!r}"
    result = call("update", sheet=PROTECTED_TAB, range="A1", value=protected_value,
                  approval_id=_approval_id(approval))
    ok, detail = expect_error(result, ["append-only or protected", "append-only", "protected"])
    if not ok and result.get("ok"):
        return False, (f"CRITICAL: write to {PROTECTED_TAB}!A1 SUCCEEDED — "
                       "append-only guard is not enforced")
    return ok, detail


def case_formula_injection(state):
    tag = nonce("FRM")
    result = call("append", tab=LOG_TAB, row=[tag, "=1+1"])
    if not result.get("ok"):
        return False, f"append failed: {result.get('error')!r}"
    try:
        found = call("search", query=tag, maxResults=50)
    except GatewayError as exc:
        return False, f"append ok but read-back failed: {exc}"
    for hit in found.get("results", []):
        values = [str(v) for v in hit.get("values", [])]
        if tag in values:
            idx = values.index(tag)
            cell = values[idx + 1] if idx + 1 < len(values) else ""
            if "1+1" in cell and cell.strip() not in {"2", "2.0"}:
                return True, f"stored as text: {cell!r}"
            return False, f"formula was evaluated or mangled: stored cell={cell!r}"
    return False, f"row {tag!r} not found in gateway scan window (check row count/columns)"


def case_duplicate_request_id(state):
    tag = nonce("DUP")
    request_id = uuid.uuid4().hex
    row = [tag, "duplicate-guard", request_id[:8]]
    first = call("append", tab=LOG_TAB, row=row, request_id=request_id)
    if not first.get("ok"):
        return False, f"first append failed: {first.get('error')!r}"
    before = search_row_count(tag, LOG_TAB)
    second = call("append", tab=LOG_TAB, row=row, request_id=request_id)
    if not second.get("ok"):
        return False, f"second append errored (expected duplicate replay): {second.get('error')!r}"
    if not second.get("duplicate"):
        return False, "second response is missing duplicate:true"
    after = search_row_count(tag, LOG_TAB)
    if before >= 0 and after >= 0 and after != before:
        return False, f"second call added a row ({before} -> {after} matching rows)"
    return True, f"duplicate:true, matching rows={after if after >= 0 else '?'} (read-back is best effort)"


def case_bad_approval_secret(state):
    result = _record_approval(state.get("update_sheet", SCRATCH_TAB), SCRATCH_RANGE,
                              nonce("BAD"), secret="intentionally-wrong-" + (APPROVAL_SECRET or "x"))
    return expect_error(result, ["approval unauthorized", "unauthorized"])


def case_upsert_labels_allowlist(state):
    """T2 regression guard: the gateway allowlist must cover every label the callers write."""
    probe = {label: "verify-suite" for label in CALLER_METRIC_LABELS}
    result = call("upsert_metrics", sheet="Executive_Brief", metrics=probe)
    if not result.get("ok"):
        return False, (f"gateway rejected caller labels: {result.get('error')!r} — "
                       "fix the allowlist in the .gs before relying on webhook-first upsert_metrics (T2)")
    return True, f"all {len(CALLER_METRIC_LABELS)} caller labels accepted (updated={result.get('updated')})"


CASES = [
    (1, "health reports ok/1.0.0/DEV", case_health),
    (2, f"append to {LOG_TAB}", case_append),
    (3, "update without approval_id is rejected", case_update_without_approval),
    (4, "self-declared approved:true is rejected", case_self_declared_approved),
    (5, "record_approval + update (same value)", case_record_then_update),
    (6, "approval is single-use", case_approval_replay),
    (7, "approval is bound to the value", case_approval_value_mismatch),
    (8, f"{PROTECTED_TAB} rejects updates (append-only)", case_protected_tab_update),
    (9, "formula payload stays text", case_formula_injection),
    (10, "request_id dedupe within window", case_duplicate_request_id),
    (11, "record_approval with wrong secret", case_bad_approval_secret),
    (12, "upsert_metrics caller labels allowed (T2 guard)", case_upsert_labels_allowlist),
]


def guard_inputs() -> str:
    if not WEBHOOK_URL or not WEBHOOK_SECRET:
        return "GOOGLE_SHEETS_WEBHOOK_URL/GOOGLE_SHEETS_WEBHOOK_SECRET must be set"
    if not APPROVAL_SECRET:
        return "GOOGLE_SHEETS_APPROVAL_SECRET must be set (record_approval fails closed without it)"
    if not DEV_SHEET_ID:
        return "SHEETS_DEV_SPREADSHEET_ID must be set — the suite refuses to guess its target"
    if DEV_SHEET_ID == LIVE_ID_GUARD:
        return f"SHEETS_DEV_SPREADSHEET_ID equals the LIVE workbook id ({LIVE_ID_GUARD[:8]}…): refusing"
    if os.environ.get("GOOGLE_SHEET_ID", "").strip() == LIVE_ID_GUARD:
        return "GOOGLE_SHEET_ID points at the LIVE workbook: refusing (set it to the DEV id)"
    if APPROVAL_SECRET == WEBHOOK_SECRET:
        return "GOOGLE_SHEETS_APPROVAL_SECRET must differ from GOOGLE_SHEETS_WEBHOOK_SECRET"
    return ""


def main() -> int:
    reason = guard_inputs()
    if reason:
        print(f"ABORTED: {reason}", file=sys.stderr)
        return 2

    print(f"Sheets Gateway v1.0 — DEV verification suite (target: {_mask(WEBHOOK_URL)})")
    print(f"scratch tab: {SCRATCH_TAB!r} · log tab: {LOG_TAB!r} · protected tab: {PROTECTED_TAB!r}\n")

    state: dict = {}
    failures = 0
    for cid, name, fn in CASES:
        if state.get("fatal"):
            print(f"[SKIP] {cid:>2}  {name} — {state['fatal']}")
            failures += 1
            continue
        try:
            passed, detail = fn(state)
        except GatewayError as exc:
            passed, detail = False, f"gateway error: {_mask(exc)}"
        except Exception as exc:  # noqa: BLE001 - harness must report, not crash
            passed, detail = False, f"suite error: {_mask(exc)}"
        failures += 0 if passed else 1
        print(f"[{'PASS' if passed else 'FAIL'}] {cid:>2}  {name} — {_mask(detail)}")

    total = len(CASES)
    print(f"\nRESULT: {total - failures}/{total} PASS")
    if state.get("fatal"):
        print(f"FATAL: {state['fatal']}")
    print("Note: Gateway_Audit rows and the scratch tab are written on purpose; "
          f"{APPROVAL_TTL_NOTE}.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

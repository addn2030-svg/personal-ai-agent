#!/usr/bin/env python3
"""Verify the Sheets Gateway v1.0 contract against an explicit DEV workbook.

This script performs the documented write checks. It refuses to start unless the
configured target ID is present, is not the known LIVE workbook, and the gateway
health response identifies the same workbook as DEV. It never prints secrets.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid


KNOWN_LIVE_SPREADSHEET_ID = "1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc"
CELL_RE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,5}$")
APPEND_ONLY_TABS = {
    "Decision_Log", "Telegram_Log", "FollowUp_Log", "Approval_Log",
    "Agent_Log", "Brief_History", "Knowledge_Log", "Audit_Log",
}
PROTECTED_TABS = {"Gateway_Audit", "Gateway_Approvals"}
CASE_TITLES = [
    "health",
    "append Agent_Log",
    "update without approval_id",
    "update with approved:true only",
    "record_approval then update with same value",
    "reuse approval_id",
    "approval/value mismatch",
    "update Audit_Log",
    "formula append is text",
    "duplicate request_id",
    "wrong approval secret",
]


class GatewayClient:
    def __init__(self, url: str, agent_secret: str):
        self.url = url
        self.agent_secret = agent_secret

    def call(self, action: str, *, auth_secret: str | None = None, **kwargs):
        payload = {
            "secret": self.agent_secret if auth_secret is None else auth_secret,
            "action": action,
            **kwargs,
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"transport error: {type(exc).__name__}") from exc
        try:
            result = json.loads(raw)
        except Exception as exc:
            raise RuntimeError("gateway returned non-JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("gateway returned a non-object response")
        return result


def _error_text(exc: Exception, client: GatewayClient) -> str:
    text = str(exc)
    for secret in (client.agent_secret, os.environ.get("GOOGLE_SHEETS_APPROVAL_SECRET", "")):
        if secret:
            text = text.replace(secret, "<redacted>")
    text = text.replace(client.url, "<webhook-url>")
    return text.replace("\n", " ")[:240]


def _require_ok(result: dict, label: str = "gateway response"):
    if result.get("ok") is not True:
        raise AssertionError(f"{label}: {result.get('error', 'not ok')}")
    return result


def _require_error(client: GatewayClient, action: str, expected: str, **kwargs):
    result = client.call(action, **kwargs)
    if result.get("ok") is not False:
        raise AssertionError(f"expected error containing {expected!r}")
    error = str(result.get("error", ""))
    if expected not in error:
        raise AssertionError(f"expected {expected!r}, got {error!r}")
    return result


def _search_marker(client: GatewayClient, marker: str):
    result = _require_ok(client.call("search", query=marker, maxResults=50), "search")
    return [item for item in result.get("results", []) if item.get("sheet") == "Agent_Log"]


def _assert_one_marker(client: GatewayClient, marker: str):
    matches = _search_marker(client, marker)
    if len(matches) != 1:
        raise AssertionError(f"expected one Agent_Log row for marker, got {len(matches)}")
    return matches[0]


def _preflight(client: GatewayClient, target_id: str, live_id: str, write_sheet: str):
    if not target_id:
        raise RuntimeError(
            "set SHEETS_GATEWAY_TARGET_SPREADSHEET_ID (or GOOGLE_SHEET_ID) to the DEV workbook ID"
        )
    if target_id == live_id or target_id == KNOWN_LIVE_SPREADSHEET_ID:
        raise RuntimeError("refusing to run: target spreadsheet is the LIVE workbook")

    health = _require_ok(client.call("health"), "health")
    if health.get("version") != "1.0.0":
        raise RuntimeError("refusing to run: gateway version is not 1.0.0")
    if health.get("env") != "DEV":
        raise RuntimeError("refusing to run: gateway environment is not DEV")
    health_id = str(health.get("spreadsheet_id") or "")
    if not health_id:
        raise RuntimeError("refusing to run: health did not identify the target spreadsheet")
    if health_id == live_id or health_id == KNOWN_LIVE_SPREADSHEET_ID:
        raise RuntimeError("refusing to run: gateway health points to the LIVE workbook")
    if health_id != target_id:
        raise RuntimeError("refusing to run: target ID does not match gateway health")

    metadata = _require_ok(client.call("metadata"), "metadata")
    titles = {str(item.get("title")) for item in metadata.get("sheets", [])}
    if write_sheet not in titles:
        raise RuntimeError(f"verification write sheet is missing: {write_sheet}")
    if write_sheet in APPEND_ONLY_TABS or write_sheet in PROTECTED_TABS:
        raise RuntimeError("verification write sheet must be writable and non-managed")
    return health


def _arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip(),
        help="DEV Apps Script web-app URL (or GOOGLE_SHEETS_WEBHOOK_URL)",
    )
    parser.add_argument(
        "--target-spreadsheet-id",
        default=(os.environ.get("SHEETS_GATEWAY_TARGET_SPREADSHEET_ID", "").strip()
                 or os.environ.get("GOOGLE_SHEET_ID", "").strip()),
        help="DEV spreadsheet ID; required to prove the target is not LIVE",
    )
    parser.add_argument(
        "--live-spreadsheet-id",
        default=(os.environ.get("SHEETS_GATEWAY_LIVE_SPREADSHEET_ID", "").strip()
                 or KNOWN_LIVE_SPREADSHEET_ID),
        help="LIVE spreadsheet ID to refuse (defaults to the configured production ID)",
    )
    parser.add_argument(
        "--sheet",
        default=os.environ.get("SHEETS_GATEWAY_VERIFY_SHEET", "Executive_Brief").strip(),
        help="writable DEV sheet for update checks",
    )
    parser.add_argument(
        "--range",
        dest="cell",
        default=os.environ.get("SHEETS_GATEWAY_VERIFY_RANGE", "ZZ1").strip().upper(),
        help="single writable DEV cell for update checks",
    )
    return parser


def main(argv=None):
    args = _arg_parser().parse_args(argv)
    agent_secret = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
    approval_secret = os.environ.get("GOOGLE_SHEETS_APPROVAL_SECRET", "").strip()

    startup_errors = []
    if not args.url:
        startup_errors.append("GOOGLE_SHEETS_WEBHOOK_URL is not configured")
    if not agent_secret:
        startup_errors.append("GOOGLE_SHEETS_WEBHOOK_SECRET is not configured")
    if not approval_secret:
        startup_errors.append("GOOGLE_SHEETS_APPROVAL_SECRET is not configured")
    if approval_secret and agent_secret and approval_secret == agent_secret:
        startup_errors.append("approval secret must differ from webhook secret")
    if not args.live_spreadsheet_id:
        startup_errors.append("live spreadsheet ID is required")
    if not CELL_RE.fullmatch(args.cell):
        startup_errors.append("verification range must be a single cell such as ZZ1")

    if startup_errors:
        message = "; ".join(startup_errors)
        for number, title in enumerate(CASE_TITLES, 1):
            print(f"FAIL {number}. {title}: {message}")
        return 2

    client = GatewayClient(args.url, agent_secret)
    try:
        health = _preflight(client, args.target_spreadsheet_id, args.live_spreadsheet_id, args.sheet)
    except Exception as exc:
        message = _error_text(exc, client)
        for number, title in enumerate(CASE_TITLES, 1):
            print(f"FAIL {number}. {title}: DEV preflight blocked all writes: {message}")
        return 2

    failures = []
    run_id = uuid.uuid4().hex[:12]
    marker = f"gateway-verify-{run_id}"
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    def case(number, title, function):
        try:
            function()
            print(f"PASS {number}. {title}")
        except Exception as exc:
            failures.append(number)
            print(f"FAIL {number}. {title}: {_error_text(exc, client)}")

    def health_contract():
        if not (
            health.get("ok") is True
            and health.get("version") == "1.0.0"
            and health.get("env") == "DEV"
        ):
            raise AssertionError("health contract mismatch")

    case(1, CASE_TITLES[0], health_contract)

    def append_agent_log():
        _require_ok(client.call(
            "append",
            tab="Agent_Log",
            row=["gateway_verify", marker, now],
            request_id=f"{marker}-append",
        ), "append Agent_Log")

    case(2, CASE_TITLES[1], append_agent_log)

    def update_without_approval():
        _require_error(
            client, "update", "approval required",
            sheet=args.sheet, range=args.cell, value=f"{marker}-no-approval",
        )

    case(3, CASE_TITLES[2], update_without_approval)

    def self_declared_approval():
        _require_error(
            client, "update", "self-declared approved:true is no longer accepted",
            sheet=args.sheet, range=args.cell, value=f"{marker}-self-approved", approved=True,
        )

    case(4, CASE_TITLES[3], self_declared_approval)

    approval_id = f"VERIFY-{run_id}"
    approved_value = f"{marker}-approved"

    def approved_update():
        _require_ok(client.call(
            "record_approval",
            approval_secret=approval_secret,
            approval_id=approval_id,
            sheet=args.sheet,
            range=args.cell,
            value=approved_value,
            approved_by="sheets-gateway-verifier",
            ttl_minutes=15,
            request_id=f"{marker}-record-approval",
        ), "record approval")
        result = _require_ok(client.call(
            "update",
            sheet=args.sheet,
            range=args.cell,
            value=approved_value,
            approval_id=approval_id,
            request_id=f"{marker}-approved-update",
        ), "approved update")
        if "before" not in result or "after" not in result:
            raise AssertionError("approved update did not return before and after")
        if result.get("after") != approved_value:
            raise AssertionError("approved update after value did not match")

    case(5, CASE_TITLES[4], approved_update)

    def reuse_approval():
        _require_error(
            client, "update", "approval already used",
            sheet=args.sheet, range=args.cell, value=approved_value, approval_id=approval_id,
        )

    case(6, CASE_TITLES[5], reuse_approval)

    mismatch_id = f"VERIFY-MISMATCH-{run_id}"
    mismatch_value = f"{marker}-bound-a"

    def mismatched_value():
        _require_ok(client.call(
            "record_approval",
            approval_secret=approval_secret,
            approval_id=mismatch_id,
            sheet=args.sheet,
            range=args.cell,
            value=mismatch_value,
            approved_by="sheets-gateway-verifier",
            ttl_minutes=15,
            request_id=f"{marker}-mismatch-approval",
        ), "record mismatch approval")
        _require_error(
            client, "update", "approval does not match value",
            sheet=args.sheet, range=args.cell, value=f"{marker}-bound-b", approval_id=mismatch_id,
        )

    case(7, CASE_TITLES[6], mismatched_value)

    def protected_audit_log():
        _require_error(
            client, "update", "tab is append-only or protected",
            sheet="Audit_Log", range="A1", value=f"{marker}-protected", approval_id="VERIFY-PROTECTED",
        )

    case(8, CASE_TITLES[7], protected_audit_log)

    formula_marker = f"{marker}-formula"

    def formula_is_text():
        _require_ok(client.call(
            "append",
            tab="Agent_Log",
            row=[formula_marker, "=1+1"],
            request_id=f"{marker}-formula-append",
        ), "formula append")
        result = _assert_one_marker(client, formula_marker)
        values = result.get("values") or []
        if len(values) < 2:
            raise AssertionError("formula row did not contain a second cell")
        display = str(values[1]).strip()
        if display in {"2", "2.0"} or display.lstrip("'") != "=1+1":
            raise AssertionError(f"formula was evaluated or changed: {display!r}")

    case(9, CASE_TITLES[8], formula_is_text)

    duplicate_marker = f"{marker}-duplicate"
    duplicate_request_id = f"{marker}-same-request"

    def duplicate_request():
        _require_ok(client.call(
            "append",
            tab="Agent_Log",
            row=[duplicate_marker, "one"],
            request_id=duplicate_request_id,
        ), "first duplicate-request append")
        second = _require_ok(client.call(
            "append",
            tab="Agent_Log",
            row=[duplicate_marker, "one"],
            request_id=duplicate_request_id,
        ), "second duplicate-request append")
        if second.get("duplicate") is not True:
            raise AssertionError("second append did not return duplicate:true")
        _assert_one_marker(client, duplicate_marker)

    case(10, CASE_TITLES[9], duplicate_request)

    def wrong_approval_secret():
        _require_error(
            client, "record_approval", "approval unauthorized",
            approval_secret="gateway-verifier-wrong-secret",
            approval_id=f"VERIFY-WRONG-{run_id}",
            sheet=args.sheet,
            range=args.cell,
            value=f"{marker}-wrong-secret",
            approved_by="sheets-gateway-verifier",
        )

    case(11, CASE_TITLES[10], wrong_approval_secret)

    if failures:
        print(f"RESULT FAIL: {len(failures)} case(s) failed")
        return 1
    print("RESULT PASS: 11/11 gateway checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

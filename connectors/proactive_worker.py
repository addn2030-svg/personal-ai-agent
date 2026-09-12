# -*- coding: utf-8 -*-
"""Bounded proactive worker for the production webhook process.

Every cycle runs two governed engines, each fail-soft so a fault in one never
takes down Telegram serving or the other:

  1. ``scheduler.dispatch_due()`` — v0.9 cron table (morning brief, focus block,
     supervisor close, audio digest, weekly/monthly reports). Without this, no
     scheduled job ever fires in production because the dedicated ``manager
     --loop`` service is not what Railway boots (Dockerfile CMD is the webhook).
  2. ``proactive.sweep()`` — v1.0 observe→remember→predict→score→decide loop.

Both engines are already idempotent on a per-cycle key (``cycle_key`` for
scheduler jobs, candidate ``key`` for proactive actions) so a 15-minute tick or
a late restart will never produce duplicate drafts.

External effects remain in ``PENDING_APPROVAL`` — same governance as always.
"""
from __future__ import annotations

import os
import threading

from engine import manager, proactive, scheduler

ENABLED_ENV = "PROACTIVE_WORKER_ENABLED"
INTERVAL_ENV = "PROACTIVE_WORKER_INTERVAL_SECONDS"
DISPATCH_SCHED_ENV = "PROACTIVE_WORKER_DISPATCH_SCHEDULER"
DEFAULT_INTERVAL_SECONDS = 900


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "1").strip() == "1" and proactive.enabled()


def interval_seconds() -> int:
    raw = os.environ.get(INTERVAL_ENV, str(DEFAULT_INTERVAL_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(60, value)


def scheduler_dispatch_enabled() -> bool:
    """Kill-switch: set PROACTIVE_WORKER_DISPATCH_SCHEDULER=0 to skip cron."""
    return os.environ.get(DISPATCH_SCHED_ENV, "1").strip() != "0"


def cycle_once() -> dict:
    """Run one governed tick: scheduled jobs (if enabled) then proactive sweep.

    Each side is fail-soft: scheduler errors are logged and don't prevent sweep,
    and vice-versa. Returns the proactive sweep summary (matches prior API);
    scheduler stats are attached under ``scheduler`` for observability.
    """
    sched_stats = {"executed": 0, "skipped": 0, "error": None}
    if scheduler_dispatch_enabled():
        try:
            executed, skipped = scheduler.dispatch_due(verbose=False)
            sched_stats["executed"] = executed
            sched_stats["skipped"] = skipped
        except Exception as exc:  # noqa: BLE001 — fail-soft; never take down Telegram
            sched_stats["error"] = str(exc)[:200]
            manager.log_event("proactive_worker_scheduler_error",
                              error=sched_stats["error"])
            print(f"Proactive worker: scheduler tick failed: {str(exc)[:180]}",
                  flush=True)
    else:
        sched_stats["disabled"] = True

    try:
        result = proactive.sweep(verbose=False)
    except Exception as exc:  # noqa: BLE001 — fail-soft; log and move on
        manager.log_event("proactive_worker_sweep_error", error=str(exc)[:200])
        print(f"Proactive worker: sweep failed: {str(exc)[:180]}", flush=True)
        result = {"sweep_error": str(exc)[:200]}

    result = dict(result) if isinstance(result, dict) else {"sweep": result}
    result["scheduler"] = sched_stats
    stamp = manager.now().isoformat(timespec="seconds")
    manager._update_markers(last_proactive_worker=stamp)
    manager.log_event("proactive_worker_cycle", at=stamp, summary=result)
    return result


def _log_startup_diagnostic():
    """Surface persistence/scheduler wiring status once at worker boot.

    Goal: never fail silently. If AI_OS_DATA_DIR is not mounted on a deploy
    platform, state.json lives inside the ephemeral container filesystem and
    every redeploy wipes proactive_cfg, standing orders, pause state, the
    automation_runs ledger (which deduplicates scheduled jobs), and the
    open-loops ledger. Emit a loud warning in both logs and /proactive status.
    """
    diag = proactive.persistence_status()
    parts = [f"interval={interval_seconds()}s",
             f"scheduler_dispatch={'on' if scheduler_dispatch_enabled() else 'off'}"]
    if diag.get("persistence", {}).get("warning"):
        warn = diag["persistence"]["warning"]
        parts.append(f"⚠️  {warn}")
        manager.log_event("proactive_worker_persistence_warning", **diag["persistence"])
        print(f"Proactive worker WARNING: {warn}", flush=True)
    return parts


def _worker(stop_event: threading.Event | None = None, sleep_seconds: float | None = None):
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else interval_seconds())
    manager.log_event("proactive_worker_started", interval_seconds=interval,
                      scheduler_dispatch=scheduler_dispatch_enabled())
    while not stop_event.is_set():
        try:
            cycle_once()
        except Exception as exc:  # fail-soft: never take down Telegram
            manager.log_event("proactive_worker_error", error=str(exc)[:300])
            print(f"Proactive worker warning: {str(exc)[:220]}", flush=True)
        if stop_event.wait(max(0.01, interval)):
            break


def start_if_enabled():
    if not enabled():
        print("Proactive worker: disabled", flush=True)
        return None
    parts = _log_startup_diagnostic()
    worker = threading.Thread(target=_worker, name="proactive-worker", daemon=True)
    worker.start()
    print("Proactive worker: active | " + " | ".join(parts), flush=True)
    return worker

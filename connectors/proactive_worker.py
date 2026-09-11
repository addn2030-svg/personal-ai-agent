# -*- coding: utf-8 -*-
"""Bounded proactive sweep worker for the production webhook process.

The worker only runs the existing governed ``proactive.sweep``. That engine may
write reversible internal state and push owner-only alerts, but external actions
remain ``PENDING_APPROVAL``. Failures are isolated from Telegram serving.
"""
from __future__ import annotations

import os
import threading

from engine import manager, proactive

ENABLED_ENV = "PROACTIVE_WORKER_ENABLED"
INTERVAL_ENV = "PROACTIVE_WORKER_INTERVAL_SECONDS"
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


def cycle_once() -> dict:
    """Run one governed sweep and persist an observable heartbeat."""
    result = proactive.sweep(verbose=False)
    stamp = manager.now().isoformat(timespec="seconds")
    manager._update_markers(last_proactive_worker=stamp)
    manager.log_event("proactive_worker_cycle", at=stamp, summary=result)
    return result


def _worker(stop_event: threading.Event | None = None, sleep_seconds: float | None = None):
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else interval_seconds())
    manager.log_event("proactive_worker_started", interval_seconds=interval)
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
    worker = threading.Thread(target=_worker, name="proactive-worker", daemon=True)
    worker.start()
    print(f"Proactive worker: active | interval={interval_seconds()}s", flush=True)
    return worker

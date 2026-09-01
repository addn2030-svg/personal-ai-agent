# -*- coding: utf-8 -*-
"""FAST-only Manager canary for the production webhook process.

This module intentionally never calls manager.full_cycle() or manager.loop().
It only runs deterministic fast_cycle() on a bounded interval when the explicit
MANAGER_FAST_CANARY_ENABLED=1 feature flag is set. Default is OFF.
"""
from __future__ import annotations

import os
import threading

from engine import manager

ENABLED_ENV = "MANAGER_FAST_CANARY_ENABLED"
INTERVAL_ENV = "MANAGER_FAST_CANARY_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 900


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "0").strip() == "1"


def interval_seconds() -> int:
    raw = os.environ.get(INTERVAL_ENV, str(DEFAULT_INTERVAL_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(60, value)


def cycle_once() -> dict:
    """Run one FAST cycle and persist a canary heartbeat; never run FULL."""
    summary = manager.fast_cycle()
    stamp = manager.now().isoformat(timespec="seconds")
    manager._update_markers(last_fast_canary=stamp)
    manager.log_event("manager_fast_canary_cycle", at=stamp, summary=summary)
    return summary


def _worker(stop_event: threading.Event | None = None, sleep_seconds: float | None = None):
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else interval_seconds())
    manager.log_event("manager_fast_canary_started", interval_seconds=interval)
    while not stop_event.is_set():
        try:
            cycle_once()
        except Exception as exc:  # fail-soft: Telegram webhook must remain alive
            manager.log_event("manager_fast_canary_error", error=str(exc)[:300])
            print(f"Manager FAST canary warning: {str(exc)[:220]}", flush=True)
        if stop_event.wait(max(0.01, interval)):
            break


def start_if_enabled():
    """Start one daemon worker only when explicitly enabled; otherwise do nothing."""
    if not enabled():
        print("Manager FAST canary: disabled", flush=True)
        return None
    worker = threading.Thread(
        target=_worker,
        name="manager-fast-canary",
        daemon=True,
    )
    worker.start()
    print(
        f"Manager FAST canary: active | interval={interval_seconds()}s | FULL cycle=disabled",
        flush=True,
    )
    return worker

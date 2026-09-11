# -*- coding: utf-8 -*-
"""In-process automatic-timing worker for the production webhook runtime.

Railway containers run the Telegram webhook only — there is no cron daemon in the
image, so a crontab entry cannot fire there. This worker gives the same schedule
(morning brief 06:30 · periodic sweep every 3h · weekly review) inside the long
lived process by calling ``engine/timing.py tick`` on a heartbeat.

Contract mirrors connectors.manager_fast_canary: explicit feature flag, daemon
thread, fail-soft (a broken cycle never kills the webhook), and zero state writes
while nothing is due (write-on-change lives in the timing engine).

Env:
  AIOS_TIMING_WORKER=0            ← disables only this in-container worker
  AIOS_TIMING_ENABLED=0           ← disables the whole timing engine (also cron)
  TIMING_TICK_SECONDS=300         ← heartbeat interval (floor 15s)
  TIMING_BRIEF_AT / TIMING_SWEEP_INTERVAL_HOURS / TIMING_REVIEW_AT … ← the schedule

Running this worker *and* an external cron entry is safe: the timing engine
de-duplicates by cycle key and holds an exclusive process lock.
"""
from __future__ import annotations

import os
import threading

try:  # نفس كائن الوحدة الذي تستخدمه وحدات engine/ والبوت — لا ازدواج في sys.modules
    import timing
except ImportError:  # pragma: no cover - حين لا يكون مجلد engine على المسار
    from engine import timing

ENABLED_ENV = "AIOS_TIMING_WORKER"
INTERVAL_ENV = "TIMING_TICK_SECONDS"
DEFAULT_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 15

_lock = threading.Lock()
_state = {"started_at": None, "ticks": 0, "jobs_run": 0, "last_error": None,
          "last_tick_at": None, "active": False}


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "1").strip() != "0"


def interval_seconds() -> int:
    raw = os.environ.get(INTERVAL_ENV, str(DEFAULT_INTERVAL_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, value)


def _mark(**updates):
    with _lock:
        _state.update(updates)


def tick_once() -> dict:
    """One scheduler tick — returns the timing engine's result (never raises)."""
    result = timing.tick(verbose=False, trigger="webhook-worker")
    ran = len(result.get("ran", []))
    with _lock:
        _state["ticks"] += 1
        _state["jobs_run"] += ran
        _state["last_tick_at"] = timing.now().isoformat(timespec="seconds")
        _state["last_error"] = None if result.get("status") != "error" else str(result)[:200]
    return result


def health() -> dict:
    """Compact status for /health and the /timing card."""
    with _lock:
        data = dict(_state)
    data["worker"] = enabled()
    data["engine"] = timing.cfg()["enabled"]
    data["interval_seconds"] = interval_seconds()
    return data


def _worker(stop_event: threading.Event | None = None, sleep_seconds: float | None = None):
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else interval_seconds())
    _mark(active=True, started_at=timing.now().isoformat(timespec="seconds"))
    timing.log_event("timing_worker_started", interval_seconds=interval)
    while not stop_event.is_set():
        try:
            tick_once()
        except Exception as exc:  # noqa: BLE001 — fail-soft: the webhook must stay alive
            _mark(last_error=str(exc)[:200])
            timing.log_event("timing_worker_error", error=str(exc)[:300])
            print(f"Timing worker warning: {str(exc)[:220]}", flush=True)
        if stop_event.wait(max(1.0, interval)):
            break
    _mark(active=False)


def start_if_enabled():
    """Start one daemon worker when enabled; otherwise report and do nothing."""
    if not enabled():
        print("Automatic timing worker: disabled", flush=True)
        return None
    if not timing.cfg()["enabled"]:
        print("Automatic timing worker: engine disabled (AIOS_TIMING_ENABLED=0)", flush=True)
        return None
    stop_event = threading.Event()
    worker = threading.Thread(
        target=_worker,
        args=(stop_event,),
        name="automatic-timing-worker",
        daemon=True,
    )
    worker.stop_event = stop_event  # type: ignore[attr-defined]
    worker.start()
    schedule = timing.cfg()
    print(
        "Automatic timing worker: active | "
        f"heartbeat={interval_seconds()}s | brief={schedule['jobs']['brief']['time']} | "
        f"sweep=every {schedule['jobs']['sweep']['interval_hours']}h | "
        f"review={schedule['jobs']['review']['time']} "
        f"(weekdays={schedule['jobs']['review']['weekday']})",
        flush=True,
    )
    return worker

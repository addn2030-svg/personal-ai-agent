# -*- coding: utf-8 -*-
"""State startup evidence — WO-2 acceptance.

Prints one line at boot proving where state actually lives and whether it is
writable, so 'the volume is attached' becomes 'the state is durable'.

    state: dir=/data exists=True version=41 writable=True backups=5 audit=1204

Import and call from telegram_webhook.py at startup:

    from connectors import state_evidence
    state_evidence.report()

Set AI_OS_REQUIRE_DURABLE_STATE=1 to fail loudly instead of degrading when the
directory is not writable.

Note on durability: engine.store.DATA_DIR comes from AI_OS_DATA_DIR, falling
back to <repo>/data. A Railway volume mounted at /data does NOT redirect it.
Mounting the volume and forgetting AI_OS_DATA_DIR yields a writable directory
inside the container image that is silently wiped on every deploy, so this
module compares the two rather than trusting RAILWAY_VOLUME_MOUNT_PATH alone.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any

from engine import store


def _writable(directory: str) -> bool:
    probe = os.path.join(directory, ".write_probe")
    try:
        os.makedirs(directory, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        return True
    except OSError:
        return False
    finally:
        # Best-effort cleanup of the probe file; ignore errors on remove.
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass


def _under(path: str, parent: str) -> bool:
    """Return True if `path` is the same as or is under `parent`.

    Robustly handles root ('/') and normalizes components. On Windows this
    returns False for paths on different drives.
    """
    if not path or not parent:
        return False
    path = os.path.abspath(path)
    parent = os.path.abspath(parent)
    try:
        # commonpath will normalize and correctly handle root '/'
        return os.path.commonpath([parent, path]) == parent
    except ValueError:
        # Different drives on Windows raise ValueError; treat as not under.
        return False


def snapshot() -> dict[str, Any]:
    """Facts about the state directory. Never raises."""
    data_dir = store.DATA_DIR
    state_path = store.STATE_PATH
    audit_path = store.AUDIT_PATH

    exists = os.path.exists(state_path)
    version = None
    records = None

    if exists:
        try:
            with open(state_path, encoding="utf-8") as handle:
                data = json.load(handle)
            version = int(data.get("meta", {}).get("version", 0) or 0)
            records = sum(len(data.get(section, [])) for section in store.SECTIONS)
        except Exception:  # noqa: BLE001
            version = -1

    audit_lines = 0
    if os.path.exists(audit_path):
        try:
            with open(audit_path, encoding="utf-8") as handle:
                audit_lines = sum(1 for _ in handle)
        except OSError:
            audit_lines = -1

    mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()

    return {
        "dir": data_dir,
        "exists": exists,
        "version": version,
        "records": records,
        "writable": _writable(data_dir),
        "backups": len(glob.glob(os.path.join(store.BACKUP_DIR, "state-*.json"))),
        "audit_entries": audit_lines,
        "mount_path": mount,
        "data_dir_env": os.environ.get("AI_OS_DATA_DIR", ""),
        # Durable only if the state directory actually lives on the volume.
        "durable": _under(data_dir, mount),
    }


def report() -> dict[str, Any]:
    """Print the startup evidence line. Returns the snapshot."""
    facts = snapshot()

    print(
        "state: dir={dir} exists={exists} version={version} writable={writable} "
        "backups={backups} audit={audit_entries}".format(**facts),
        flush=True,
    )

    if not facts["writable"]:
        print(
            "state: WARNING — directory is NOT writable. "
            "Every state change will be lost.",
            flush=True,
        )
        if os.environ.get("AI_OS_REQUIRE_DURABLE_STATE", "").strip() == "1":
            raise RuntimeError(f"State directory {facts['dir']} is not writable")

    elif not facts["durable"]:
        if facts["mount_path"]:
            print(
                "state: WARNING — volume is mounted at {mount_path} but state lives in "
                "{dir}. Writes succeed and are wiped on every deploy. "
                "Set AI_OS_DATA_DIR={mount_path}".format(**facts),
                flush=True,
            )
        else:
            print(
                "state: WARNING — no Railway volume detected. "
                "State is ephemeral and resets on every deploy.",
                flush=True,
            )
        if os.environ.get("AI_OS_REQUIRE_DURABLE_STATE", "").strip() == "1":
            raise RuntimeError(
                f"State directory {facts['dir']} is not on a durable volume"
            )

    return facts

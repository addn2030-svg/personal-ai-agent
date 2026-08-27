# -*- coding: utf-8 -*-
"""State Store — operational source of truth.

Safety guarantees:
- atomic state replacement;
- optimistic version check for legacy commit callers;
- in-process writer serialization;
- cross-process file lock for read-modify-write transactions;
- rotating backups that COPY the previous state (never move it away first);
- audit.jsonl entry for every committed state mutation.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import glob
import json
import os
import re
import shutil
import threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("AI_OS_DATA_DIR", os.path.join(BASE, "data"))
STATE_PATH = os.path.join(DATA_DIR, "state.json")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.jsonl")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
LOCK_PATH = os.path.join(DATA_DIR, ".state.lock")

SECTIONS = ["tasks", "projects", "leads", "kpis", "meetings", "decisions",
            "followups", "voice", "learning", "finance", "waiting_for", "action_queue",
            "voice_calls", "contacts", "handoff_requests", "decision_requests",
            "learning_plans", "learning_concepts", "learning_reviews", "knowledge_sources",
            "weakness_protocols", "asset_registry", "okrs", "energy_log", "finance_ebsi",
            "unified_inbox", "fact_registry", "contradictions", "decision_reviews",
            "connector_health", "telemetry", "trust_snapshots", "conversation_memory",
            "ai_sources"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2})?$")
_WRITER_LOCK = threading.RLock()
_AUDIT_LOCK = threading.Lock()


def _default(obj):
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    raise TypeError(f"غير قابل للتسلسل: {type(obj)}")


def parse_dates(obj):
    if isinstance(obj, dict):
        return {k: parse_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [parse_dates(v) for v in obj]
    if isinstance(obj, str):
        if _DATE_RE.match(obj):
            return dt.date.fromisoformat(obj)
        if _DATETIME_RE.match(obj):
            return dt.datetime.fromisoformat(obj.replace("T", " "))
    return obj


def _write_audit(path, event, **details):
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "event": event}
    entry.update(details)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _AUDIT_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=_default) + "\n")


def log_event(event, **details):
    """Compatibility audit logger for non-Store events."""
    _write_audit(AUDIT_PATH, event, **details)


def _empty_state():
    return {
        "meta": {"version": 0, "updated_at": None, "schema": "state/1", "note": ""},
        **{s: [] for s in SECTIONS},
        "manager_markers": {},
    }


@contextlib.contextmanager
def _process_file_lock(path):
    """Exclusive cross-process lock; flock on Railway/Linux, msvcrt on Windows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if os.path.getsize(path) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class Store:
    def __init__(self, path=STATE_PATH):
        self.path = path
        self.data_dir = os.path.dirname(path)
        self.audit_path = os.path.join(self.data_dir, "audit.jsonl")
        self.backup_dir = os.path.join(self.data_dir, "backups")
        self.lock_path = os.path.join(self.data_dir, ".state.lock")
        self._base_version = -1
        self.data = self._read_unlocked()

    def _read_unlocked(self):
        if not os.path.exists(self.path):
            self._base_version = 0
            return _empty_state()
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        for s in SECTIONS:
            data.setdefault(s, [])
        data.setdefault("manager_markers", {})
        data.setdefault("meta", {})
        self._base_version = int(data["meta"].get("version", 0) or 0)
        return data

    def reload(self):
        with _WRITER_LOCK, _process_file_lock(self.lock_path):
            self.data = self._read_unlocked()
        return self

    def rows_all(self):
        return parse_dates(copy.deepcopy(self.data))

    def record_count(self):
        return sum(len(self.data.get(section, [])) for section in SECTIONS)

    def validate(self, require_nonempty=True):
        errors = []
        if not os.path.exists(self.path):
            errors.append("state.json is missing")
        if self.data.get("meta", {}).get("schema") != "state/1":
            errors.append("unsupported state schema")
        for section in SECTIONS:
            if not isinstance(self.data.get(section), list):
                errors.append(f"section {section} must be a list")
        if not isinstance(self.data.get("manager_markers"), dict):
            errors.append("manager_markers must be an object")
        if require_nonempty and self.record_count() == 0:
            errors.append("state store is empty")
        if errors:
            raise RuntimeError("State validation failed: " + "; ".join(errors))
        return True

    def transaction(self, change_fn, mutator, **details):
        """Serialize the complete read-modify-write sequence.

        change_fn receives a fresh parsed copy and returns either:
          (changed: bool, result)
        or a truthy/falsy value used as both changed and result.
        """
        with _WRITER_LOCK, _process_file_lock(self.lock_path):
            self.data = self._read_unlocked()
            working = parse_dates(copy.deepcopy(self.data))
            outcome = change_fn(working)
            if isinstance(outcome, tuple) and len(outcome) == 2:
                changed, result = bool(outcome[0]), outcome[1]
            else:
                changed, result = bool(outcome), outcome
            if changed:
                self._commit_locked(working, mutator, **details)
            return result

    def commit(self, new_data, mutator, **details):
        """Legacy commit API, now protected by thread + process locks."""
        with _WRITER_LOCK, _process_file_lock(self.lock_path):
            current_version = self._disk_version_unlocked()
            if current_version != self._base_version:
                raise RuntimeError(
                    f"تعارض كتابة: الملف على القرص v{current_version} بينما النسخة المقروءة v{self._base_version}. "
                    "استخدم Store.transaction لعمليات read-modify-write المتزامنة.")
            self._commit_locked(new_data, mutator, **details)

    def _commit_locked(self, new_data, mutator, **details):
        for section in SECTIONS:
            new_data.setdefault(section, [])
        new_data.setdefault("manager_markers", {})
        version = self._base_version + 1
        new_data["meta"] = {
            "version": version,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "schema": "state/1",
            "last_mutator": mutator,
        }
        self._backup_unlocked()
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.path + f".tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=1, default=_default)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self._base_version = version
        self.data = copy.deepcopy(new_data)
        _write_audit(self.audit_path, "state_commit", mutator=mutator, version=version, **details)

    def _disk_version_unlocked(self):
        if not os.path.exists(self.path):
            return 0
        try:
            with open(self.path, encoding="utf-8") as f:
                return int(json.load(f)["meta"].get("version", 0) or 0)
        except Exception:
            return -1

    def _backup_unlocked(self):
        if not os.path.exists(self.path):
            return
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = os.path.join(self.backup_dir, f"state-{stamp}.json")
        try:
            shutil.copy2(self.path, target)
        except OSError:
            return
        backups = sorted(glob.glob(os.path.join(self.backup_dir, "state-*.json")))
        for old in backups[:-5]:
            try:
                os.remove(old)
            except OSError:
                pass

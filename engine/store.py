# -*- coding: utf-8 -*-
"""
State Store — مصدر الحقيقة الموحد (إصلاح C1).
قاعدة واحدة صارمة: كل البيانات القابلة للتغيير هنا فقط، وبكاتب واحد (single-writer):
  - كتابة ذرّية (ملف مؤقت + استبدال)
  - رقم إصدار يرفض الكتابة فوق نسخة أحدث (كشف تعارض)
  - نسخ احتياطية دوّارة (آخر 5)
  - سجل تدقيق audit.jsonl لكل عملية كتابة
"""
import copy
import datetime as dt
import glob
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE, "data", "state.json")
AUDIT_PATH = os.path.join(BASE, "data", "audit.jsonl")
BACKUP_DIR = os.path.join(BASE, "data", "backups")

SECTIONS = ["tasks", "projects", "leads", "kpis", "meetings", "decisions",
            "followups", "voice", "learning", "finance", "waiting_for", "action_queue",
            "voice_calls", "contacts", "handoff_requests", "decision_requests",
            "learning_plans", "learning_concepts", "learning_reviews", "knowledge_sources"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")


def _default(obj):
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    raise TypeError(f"غير قابل للتسلسل: {type(obj)}")


def parse_dates(obj):
    """يحوّل سلاسل ISO إلى تاريخ/تاريخ-وقت عند القراءة."""
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


def log_event(event, **details):
    """سجل تدقيق — سطر JSON لكل حدث مهم."""
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "event": event}
    entry.update(details)
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=_default) + "\n")


def _empty_state():
    return {"meta": {"version": 0, "updated_at": None, "schema": "state/1", "note": ""},
            **{s: [] for s in SECTIONS}}


class Store:
    def __init__(self, path=STATE_PATH):
        self.path = path
        self._base_version = -1
        self.data = self._read()

    def _read(self):
        if not os.path.exists(self.path):
            self._base_version = 0
            return _empty_state()
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        for s in SECTIONS:
            data.setdefault(s, [])
        data.setdefault("meta", {})
        self._base_version = data["meta"].get("version", 0)
        return data

    # ------- قراءة -------
    def rows_all(self):
        """نسخة مفحوصة (مع التواريخ ككائنات date) من كل الأقسام."""
        return parse_dates(copy.deepcopy(self.data))

    # ------- كتابة -------
    def commit(self, new_data, mutator, **details):
        """الكاتب الوحيد: يرفض الكتابة إن تغيّر الملف منذ آخر قراءة."""
        current_version = self._disk_version()
        if current_version != self._base_version:
            raise RuntimeError(
                f"تعارض كتابة: الملف على القرص v{current_version} بينما كتبنا فوق v{self._base_version}. "
                "أعد التحميل ثم نفّذ التغيير (قاعدة الكاتب الواحد).")
        version = self._base_version + 1
        new_data["meta"] = {
            "version": version,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "schema": "state/1",
            "last_mutator": mutator,
        }
        self._backup()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=1, default=_default)
        os.replace(tmp, self.path)
        self._base_version = version
        self.data = new_data
        log_event("state_commit", mutator=mutator, version=version, **details)

    def _disk_version(self):
        if not os.path.exists(self.path):
            return 0
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)["meta"].get("version", 0)
        except Exception:
            return -1

    def _backup(self):
        if not os.path.exists(self.path):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            os.replace(self.path, os.path.join(BACKUP_DIR, f"state-{stamp}.json"))
        except OSError:
            return
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "state-*.json")))
        for old in backups[:-5]:
            os.remove(old)

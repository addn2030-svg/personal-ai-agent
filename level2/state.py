# -*- coding: utf-8 -*-
"""
مخزن الحالة المحلي — بديل Google Sheets وSupabase بالكامل.

مصدر حقيقة واحد: ملف JSON محلي (افتراضيًا level2/data/level2_state.json)
  • كتابة ذرّية (tmp + os.replace) — لا ملفات مقطوعة أبدًا
  • نسخ دوّارة تلقائية (7 نسخ) — بديل النسخ السحابي، على قرصك أنت
  • لا شبكة، لا مفاتيح، لا اعتماديات خارجية

البنية: tasks / decisions / waiting_for / sessions / reviews / energy_log /
possibilities / settings
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.environ.get(
    "LEVEL2_STATE_PATH", os.path.join(BASE_DIR, "data", "level2_state.json")
)
BACKUP_COUNT = 7

_LOCK = threading.RLock()

# ── أدوات الوقت ──────────────────────────────────────────────────────────────

def now() -> dt.datetime:
    tz = os.environ.get("LEVEL2_TZ", "Asia/Riyadh")
    try:
        import zoneinfo
        return dt.datetime.now(zoneinfo.ZoneInfo(tz))
    except Exception:
        return dt.datetime.now()


def today_iso() -> str:
    return now().date().isoformat()


def parse_date(text: str | None):
    """تاريخ بسيط: YYYY-MM-DD أو DD/MM أو كلمات اليوم/غدًا/بعد غد. يرجع date أو None."""
    if not text:
        return None
    t = text.strip()
    try:
        return dt.date.fromisoformat(t[:10])
    except ValueError:
        pass
    low = t.lower()
    base = now().date()
    if "بعد غد" in low or "after tomorrow" in low:
        return base + dt.timedelta(days=2)
    if "غدا" in low or "غدًا" in low or "tomorrow" in low:
        return base + dt.timedelta(days=1)
    if "اليوم" in low or "today" in low:
        return base
    for sep in ("/", "-"):
        parts = low.split(sep)
        if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) <= 2:
            d, m, y = parts
            y = int(y)
            y = y + 2000 if y < 100 else y
            try:
                return dt.date(y, int(m), int(d))
            except ValueError:
                continue
        if len(parts) == 2 and all(p.isdigit() and 1 <= len(p) <= 2 for p in parts):
            # 15/10 ⇒ يوم/شهر من السنة الحالية
            d, m = int(parts[0]), int(parts[1])
            base = now().date()
            try:
                cand = dt.date(base.year, m, d)
                return cand if cand >= base else cand.replace(year=base.year + 1)
            except ValueError:
                continue
    return None


# ── المخزن ───────────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "version": 1,
        "created_at": now().isoformat(timespec="seconds"),
        "owner": "Abdulrahman",
        "tasks": [],
        "decisions": [],
        "waiting_for": [],
        "possibilities": [],
        "reviews": [],
        "energy_log": [],
        "sessions": [],
        "settings": {
            "voice_enabled": True,
            "language": "ar",
            "weekly_review_day": 4,  # الجمعة (الاثنين=0)
            "max_alerts_per_day": 6,
        },
    }


class Level2Store:
    """كاتب واحد للحالة — كل التعديلات تمر عبره مع قفل وقفل ذرّي على القرص."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._save(_empty_state())
        self._state = self._load()

    # ── قراءة/كتابة القرص ──
    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # الفشل ينغلق على الأأمن: ملف تالف ⇒ نسخة احتياطية جديدة فارغة،
            # والقديم يبقى محفوظًا بجواره (.corrupt-*) فلا ضياع بيانات.
            try:
                os.replace(self.path, self.path + f".corrupt-{uuid.uuid4().hex[:6]}")
            except OSError:
                pass
            fresh = _empty_state()
            self._save(fresh)
            return fresh

    def _save(self, state: dict) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(self.path), prefix=".l2-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._rotate()

    def _rotate(self) -> None:
        """نسخ دوّرة محلية (بديل Supabase backup): keep آخر 7."""
        try:
            stamp = now().strftime("%Y%m%d-%H%M%S")
            bak = f"{self.path}.{stamp}.bak"
            if not any(os.path.basename(p).startswith(os.path.basename(self.path) + ".") and p.endswith(".bak") for p in os.listdir(os.path.dirname(self.path))):
                with open(self.path, "r", encoding="utf-8") as src, open(bak, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            baks = sorted(
                p for p in os.listdir(os.path.dirname(self.path))
                if p.startswith(os.path.basename(self.path) + ".") and p.endswith(".bak")
            )
            for old in baks[:-BACKUP_COUNT]:
                os.unlink(os.path.join(os.path.dirname(self.path), old))
        except OSError:
            pass

    def commit(self) -> None:
        """احفظ التغييرات المعلقة (تُنادى تلقائيًا بعد كل عملية كتابة)."""
        with _LOCK:
            self._state["updated_at"] = now().isoformat(timespec="seconds")
            self._save(self._state)

    # ── المهام ──
    TASK_STATUSES = {"قيد التنفيذ", "قيد التخطيط", "قيد الفحص", "مكتمل", "ملغى", "مفتوح"}

    def add_task(self, title: str, area: str = "شخصي", importance: str = "عالي",
                 urgency: str = "متوسط", due: str | None = None,
                 next_step: str | None = None, project: str | None = None) -> dict:
        with _LOCK:
            task = {
                "id": f"T-{uuid.uuid4().hex[:6].upper()}",
                "title": title.strip(),
                "area": area,
                "importance": importance,
                "urgency": urgency,
                "status": "مفتوح",
                "due": due,
                "next_step": next_step or "حدد أول خطوة عملية اليوم",
                "project": project,
                "evidence": None,
                "created": now().isoformat(timespec="seconds"),
                "updated": now().isoformat(timespec="seconds"),
            }
            self._state["tasks"].append(task)
            self.commit()
            return task

    def update_task(self, task_id: str, **fields) -> dict | None:
        with _LOCK:
            for t in self._state["tasks"]:
                if t["id"].upper() == task_id.upper():
                    t.update({k: v for k, v in fields.items() if k in t})
                    t["updated"] = now().isoformat(timespec="seconds")
                    self.commit()
                    return t
        return None

    def complete_task(self, task_id: str, evidence: str | None = None) -> dict | None:
        return self.update_task(task_id, status="مكتمل", evidence=evidence or "بدون دليل موثق")

    def find_tasks(self, query: str):
        q = query.strip().lower()
        return [t for t in self.tasks_open() if q in (t.get("title") or "").lower()]

    def tasks_open(self) -> list[dict]:
        return [t for t in self._state["tasks"] if t.get("status") not in ("مكتمل", "ملغى")]

    def tasks_overdue(self) -> list[dict]:
        out = []
        for t in self.tasks_open():
            d = parse_date(t.get("due"))
            if d and d < now().date():
                out.append(t)
        return out

    def top_priorities(self, n: int = 2) -> list[dict]:
        """أولويات اليوم: متأخرة أولًا، ثم عالية الأهمية/الإلحاح، ثم الأقدم."""
        def score(t):
            d = parse_date(t.get("due"))
            overdue = 2 if (d and d < now().date()) else 0
            imp = {"عالي": 4, "متوسط": 2, "منخفض": 1}.get(t.get("importance"), 2)
            urg = {"عالي": 3, "متوسط": 1.5, "منخفض": 0.5}.get(t.get("urgency"), 1.5)
            return overdue + imp + urg
        return sorted(self.tasks_open(), key=score, reverse=True)[:n]

    # ── القرارات ──
    def add_decision(self, title: str, domain: str = "عام", option: str | None = None,
                     confidence: int = 70, reversible: bool = True,
                     deadline_hours: int = 24) -> dict:
        with _LOCK:
            dec = {
                "id": f"D-{uuid.uuid4().hex[:6].upper()}",
                "title": title.strip(),
                "domain": domain,
                "option": option,
                "criteria": [],
                "confidence": confidence,
                "reversible": reversible,
                "deadline": (now() + dt.timedelta(hours=deadline_hours)).isoformat(timespec="seconds"),
                "status": "قيد الحسم",
                "first_physical_action": None,   # قاعدة الـ 48 ساعة
                "created": now().isoformat(timespec="seconds"),
                "closed": None,
            }
            self._state["decisions"].append(dec)
            self.commit()
            return dec

    def close_decision(self, dec_id: str, option: str | None = None,
                       action: str | None = None) -> dict | None:
        with _LOCK:
            for d in self._state["decisions"]:
                if d["id"].upper() == dec_id.upper():
                    d["status"] = "محسوم"
                    if option:
                        d["option"] = option
                    d["first_physical_action"] = action or d.get("first_physical_action")
                    d["closed"] = now().isoformat(timespec="seconds")
                    self.commit()
                    return d
        return None

    def decisions_pending(self) -> list[dict]:
        return [d for d in self._state["decisions"] if d.get("status") != "محسوم"]

    # ── الانتظار ──
    def add_waiting(self, item: str, who: str, expected: str | None = None) -> dict:
        with _LOCK:
            w = {
                "id": f"W-{uuid.uuid4().hex[:6].upper()}",
                "item": item.strip(),
                "waiting_on": who.strip(),
                "requested": today_iso(),
                "expected": expected,
                "followups": 0,
                "status": "بانتظار",
            }
            self._state["waiting_for"].append(w)
            self.commit()
            return w

    def close_waiting(self, w_id: str) -> dict | None:
        with _LOCK:
            for w in self._state["waiting_for"]:
                if w["id"].upper() == w_id.upper():
                    w["status"] = "مغلق"
                    w["closed"] = today_iso()
                    self.commit()
                    return w
        return None

    def waiting_open(self, stale_days: int = 14) -> tuple[list[dict], list[dict]]:
        open_items, stale = [], []
        for w in self._state["waiting_for"]:
            if w.get("status") == "بانتظار":
                open_items.append(w)
                req = parse_date(w.get("requested"))
                if req and (now().date() - req).days >= stale_days:
                    stale.append(w)
        return open_items, stale

    # ── صندوق الاحتمالات (فلترة المبادرات الجديدة — قاعدة M6) ──
    def add_possibility(self, idea: str) -> dict:
        with _LOCK:
            p = {
                "id": f"P-{uuid.uuid4().hex[:6].upper()}",
                "idea": idea.strip(),
                "captured": now().isoformat(timespec="seconds"),
                "status": "جديد",
                "decision": None,
            }
            self._state["possibilities"].append(p)
            self.commit()
            return p

    # ── الطاقة ──
    def log_energy(self, energy: int, fatigue: int | None = None,
                   note: str | None = None) -> dict:
        with _LOCK:
            e = {
                "date": today_iso(),
                "energy": energy,
                "fatigue": fatigue if fatigue is not None else (10 - energy),
                "note": note,
            }
            self._state["energy_log"].append(e)
            self.commit()
            return e

    def last_energy(self) -> dict | None:
        return self._state["energy_log"][-1] if self._state["energy_log"] else None

    # ── جلسات الحوار ──
    def start_session(self, channel: str = "web") -> str:
        with _LOCK:
            sid = f"S-{uuid.uuid4().hex[:6].upper()}"
            self._state["sessions"].append({
                "id": sid, "channel": channel,
                "started": now().isoformat(timespec="seconds"),
                "exchanges": [],
            })
            self.commit()
            return sid

    def add_exchange(self, session_id: str, user_text: str, agent_reply: str,
                     intent: str) -> None:
        with _LOCK:
            for s in self._state["sessions"]:
                if s["id"] == session_id:
                    s["exchanges"].append({
                        "at": now().isoformat(timespec="seconds"),
                        "user": user_text[:500],
                        "agent": agent_reply[:1000],
                        "intent": intent,
                    })
                    break
            self.commit()

    # ── المراجعة الأسبوعية ──
    def weekly_stats(self) -> dict:
        week_ago = now() - dt.timedelta(days=7)
        tasks_done = [
            t for t in self._state["tasks"]
            if t.get("status") == "مكتمل" and t.get("updated", "") >= week_ago.isoformat()
        ]
        decisions_closed = [
            d for d in self._state["decisions"]
            if d.get("status") == "محسوم" and (d.get("closed") or "") >= week_ago.isoformat()
        ]
        return {
            "tasks_completed": len(tasks_done),
            "decisions_closed": len(decisions_closed),
            "tasks_open": len(self.tasks_open()),
            "tasks_overdue": len(self.tasks_overdue()),
            "decisions_pending": len(self.decisions_pending()),
            "energy_avg": (
                sum(e["energy"] for e in self._state["energy_log"][-7:]) / max(1, len(self._state["energy_log"][-7:]))
                if self._state["energy_log"] else None
            ),
        }

    def save_review(self, review: dict) -> dict:
        with _LOCK:
            review["date"] = today_iso()
            self._state["reviews"].append(review)
            self.commit()
            return review

    # ── لقطات عامة ──
    def brief(self) -> dict:
        """بريف مركز (قاعدة M3): أولويتان + قرار واحد + عدادات سريعة."""
        pending = self.decisions_pending()
        open_w, stale_w = self.waiting_open()
        last_e = self.last_energy()
        return {
            "date": today_iso(),
            "priorities": self.top_priorities(2),
            "pending_decision": pending[0] if pending else None,
            "tasks_open": len(self.tasks_open()),
            "tasks_overdue": len(self.tasks_overdue()),
            "decisions_pending": len(pending),
            "waiting_open": len(open_w),
            "waiting_stale": len(stale_w),
            "last_energy": last_e,
        }

    def snapshot(self) -> dict:
        return self._state


# مخزن وحيد مشترك للعملية
_store: Level2Store | None = None


def get_store() -> Level2Store:
    global _store
    if _store is None:
        # المسار يُقرأ عند أول استخدام (لا عند الاستيراد) حتى يمكن للبيئة/الاختبارات توجيهه
        path = os.environ.get("LEVEL2_STATE_PATH") or DEFAULT_PATH
        _store = Level2Store(path)
    return _store

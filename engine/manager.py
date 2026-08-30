# -*- coding: utf-8 -*-
"""Manager Loop — deterministic fast/full cycles with persistent StateStore markers.

The manager never owns a second state file. All operational mutations and loop
markers are committed through Store.transaction so concurrent webhook/manager
threads cannot perform an unsafe read-modify-write sequence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

FAST_INTERVAL = int(os.environ.get("MANAGER_CYCLE_INTERVAL_SECONDS", "900"))
MORNING_HOUR = int(os.environ.get("MANAGER_MORNING_HOUR", "6"))
MORNING_MINUTE = int(os.environ.get("MANAGER_MORNING_MINUTE", "0"))
TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
STALLED_DAYS = int(os.environ.get("MANAGER_STALLED_DAYS", "30"))
DR_COOLDOWN_DAYS = 7
NEEDS_INPUT = "NEEDS_INPUT"

now = lambda: dt.datetime.now(TZ)


def _hash(txt):
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def _as_date(x):
    """Return a date only for confirmed parseable values; unknowns stay unknown."""
    if x in (None, "", NEEDS_INPUT):
        return None
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def normalize_waiting(S):
    """Normalize legacy waiting rows without destroying WO-8 provenance/link fields."""
    changed = False
    for i, w in enumerate(S["waiting_for"]):
        if w.get("schema_version") == 2:
            continue
        task = w.get("task") or w.get("item") or w.get("title") or f"عنصر انتظار {i + 1}"
        raw_due = w.get("expected_by") or w.get("since") or w.get("expected_date")
        since = raw_due if raw_due not in (None, "") else NEEDS_INPUT
        normalized = dict(w)
        normalized.update({
            "schema_version": 2,
            "wid": w.get("wid") or "W-" + _hash(str(task))[:6],
            "task": task,
            "project_id": w.get("project_id"),
            "expected_from": w.get("expected_from", NEEDS_INPUT),
            "expected_by": since,
            "follow_up_draft": w.get("follow_up_draft"),
            "status": w.get("status") or "WAITING",
            "source": w.get("source", ""),
            "item": task,
            "since": w.get("since") or since,
        })
        S["waiting_for"][i] = normalized
        changed = True
    return changed


def _mutate_fast(S):
    changed = normalize_waiting(S)
    t = now()
    summary = {"overdue": 0, "actions": 0, "drs": 0, "superseded": 0, "expired": 0}
    events = []

    queue = S.get("action_queue", [])
    for w in S["waiting_for"]:
        if w.get("status") != "WAITING":
            continue
        due_date = _as_date(w.get("expected_by"))
        # Unknown expected dates are not guessed and therefore cannot be called overdue.
        if due_date is None or due_date >= t.date():
            continue
        w["status"] = "OVERDUE"
        changed = True
        summary["overdue"] += 1
        draft = w.get("follow_up_draft") or f"السلام عليكم، أتابع بخصوص «{w['task']}» — هل من تحديث؟ (عبدالرحمن)"
        content = (
            f"متابعة متأخرة: {w['task']}\n"
            f"كان متوقعًا من: {w.get('expected_from') or '—'} بحلول {due_date.isoformat()}\n"
            f"المسودة المقترحة:\n{draft}"
        )
        h = _hash(content)
        if not any(a.get("content_hash") == h for a in queue):
            queue.append({
                "action_id": f"A-{len(queue) + 1:03d}",
                "type": "send_followup_message",
                "channel": "wa/email",
                "content": content,
                "content_hash": h,
                "status": "PENDING_APPROVAL",
                "created_at": t.date().isoformat(),
                "expires_at": (t.date() + dt.timedelta(days=2)).isoformat(),
                "approved_at": None,
                "executed_at": None,
            })
            summary["actions"] += 1
            events.append(("action_enqueued", {"action_id": queue[-1]["action_id"], "hash": h, "origin": "manager_fast"}))

    for a in queue:
        expiry = _as_date(a.get("expires_at"))
        if a.get("status") == "PENDING_APPROVAL" and expiry and expiry < t.date():
            a["status"] = "EXPIRED"
            changed = True
            summary["expired"] += 1

    for x in S.get("learning_reviews", []):
        due_date = _as_date(x.get("due_date"))
        if x.get("status") == "SCHEDULED" and due_date and due_date <= t.date():
            x["status"] = "DUE"
            changed = True
            events.append(("REVIEW_DUE", {"review": x.get("review_id")}))

    drs = S.get("decision_requests", [])
    stalled = []
    for p in S["projects"]:
        last_progress = _as_date(p.get("آخر تقدم"))
        if (
            p.get("الحالة") == "نشط"
            and last_progress
            and last_progress < t.date() - dt.timedelta(days=STALLED_DAYS)
        ):
            stalled.append((p, last_progress))
    stalled_names = {p.get("المشروع") for p, _ in stalled}
    for dr in drs:
        if dr.get("status") == "PENDING" and dr.get("project") and dr.get("project") not in stalled_names:
            dr["status"] = "SUPERSEDED"
            changed = True
            summary["superseded"] += 1

    for p, last_progress in stalled:
        name = p["المشروع"]
        recent = []
        for d in drs:
            if d.get("project") != name:
                continue
            event_date = _as_date(d.get("resolved_at") or d.get("created_at"))
            if event_date and event_date >= t.date() - dt.timedelta(days=DR_COOLDOWN_DAYS):
                recent.append(d)
        pending = [d for d in drs if d.get("project") == name and d.get("status") == "PENDING"]
        if recent or pending:
            continue
        drs.append({
            "id": f"DR-{len(drs) + 1:03d}",
            "project": name,
            "title": f"قرار مشروع متوقف: {name}",
            "context": (
                f"حالته «نشط» لكن آخر تقدم قبل {last_progress.isoformat()} "
                f"({(t.date() - last_progress).days} يومًا)"
            ),
            "options": [
                "استئناف بخطوة واحدة محددة هذا الأسبوع",
                "تحويل الحالة إلى «متوقف»",
                "إغلاق وأرشفة",
            ],
            "deadline": (t.date() + dt.timedelta(days=1)).isoformat(),
            "status": "PENDING",
            "created_at": t.date().isoformat(),
            "resolved_at": None,
            "resolution": None,
        })
        changed = True
        summary["drs"] += 1
        events.append(("decision_request_created", {"dr": drs[-1]["id"], "project": name}))

    S["action_queue"] = queue
    S["decision_requests"] = drs
    return changed, (summary, events)


def fast_cycle():
    store = Store()
    summary, events = store.transaction(_mutate_fast, "manager_fast")
    for event, details in events:
        log_event(event, **details)
    if any(summary.values()):
        print(
            f"⚡ دورة سريعة: متأخر={summary['overdue']} | إجراءات جديدة={summary['actions']} | "
            f"طلبات قرار={summary['drs']} | منتهية={summary['expired']} | متجاوزة={summary['superseded']}"
        )
    else:
        print("⚡ دورة سريعة: لا تغييرات (لا كتابة في الحالة — write-on-change)")
    return summary


def full_cycle():
    fast_cycle()
    subprocess.run(
        [sys.executable, os.path.join(BASE, "engine", "asset_registry.py")],
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, os.path.join(BASE, "engine", "chief_of_staff.py")],
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("chief_of_staff full cycle failed")


def resolve_dr(dr_id, option_no, note):
    def mutate(S):
        dr = next(
            (d for d in S.get("decision_requests", []) if d.get("id") == dr_id and d.get("status") == "PENDING"),
            None,
        )
        if not dr:
            raise ValueError(f"لا يوجد طلب قرار مفتوح بالمعرف {dr_id}")
        if option_no < 1 or option_no > len(dr.get("options", [])):
            raise ValueError(f"الخيار {option_no} غير موجود")
        choice = dr["options"][option_no - 1]
        dr["status"] = "RESOLVED"
        dr["resolved_at"] = now().date().isoformat()
        dr["resolution"] = choice
        if option_no == 2 and dr.get("project"):
            for p in S["projects"]:
                if p.get("المشروع") == dr["project"]:
                    p["الحالة"] = "متوقف"
                    p["ملاحظات"] = (
                        str(p.get("ملاحظات") or "") + f" | حُوّل إلى متوقف بقرار {dr['id']}"
                    ).strip(" |")
        S["decisions"].append({
            "التاريخ": now().date(),
            "القرار": dr["title"],
            "البدائل المدروسة": " / ".join(dr["options"]),
            "الخيار": choice,
            "النتيجة المتوقعة": "",
            "تاريخ المراجعة": now().date() + dt.timedelta(days=30),
            "النتيجة الفعلية": None,
            "الحالة": "منفذ",
            "التقييم/الدرس": note or f"من طلب قرار {dr['id']}",
        })
        return True, choice

    choice = Store().transaction(mutate, "decision_resolved", dr=dr_id)
    log_event("decision_resolved", dr=dr_id, option_no=option_no)
    print(f"✅ {dr_id} → «{choice}» + سُجل في سجل القرارات (مراجعة بعد 30 يومًا)")


def _markers():
    return dict(Store().rows_all().get("manager_markers", {}))


def _update_markers(**updates):
    def mutate(S):
        markers = dict(S.get("manager_markers", {}))
        changed = False
        for key, value in updates.items():
            if markers.get(key) != value:
                markers[key] = value
                changed = True
        S["manager_markers"] = markers
        return changed, markers

    return Store().transaction(mutate, "manager_markers", keys=sorted(updates))


def loop():
    print(
        f"🔁 حلقة المدير: سريع كل {FAST_INTERVAL // 60} دقيقة | كامل "
        f"{MORNING_HOUR:02d}:{MORNING_MINUTE:02d} {TZ} | Ctrl+C للإيقاف"
    )
    while True:
        t = now()
        markers = _markers()
        if markers.get("hb_day") != t.date().isoformat():
            markers = _update_markers(hb_day=t.date().isoformat())
            log_event("manager_loop_alive", tz=str(TZ))

        due_full = t.replace(hour=MORNING_HOUR, minute=MORNING_MINUTE, second=0, microsecond=0)
        if t >= due_full and markers.get("last_full") != t.date().isoformat():
            try:
                full_cycle()
                _update_markers(last_full=t.date().isoformat(), last_fast=t.isoformat(timespec="seconds"))
            except Exception as exc:
                log_event("manager_full_error", error=str(exc))
        else:
            last_fast = markers.get("last_fast")
            due_fast = not last_fast
            if last_fast:
                try:
                    previous = dt.datetime.fromisoformat(last_fast)
                    if previous.tzinfo is None:
                        previous = previous.replace(tzinfo=TZ)
                    due_fast = (t - previous).total_seconds() >= FAST_INTERVAL
                except ValueError:
                    due_fast = True
            if due_fast:
                try:
                    fast_cycle()
                    _update_markers(last_fast=t.isoformat(timespec="seconds"))
                except Exception as exc:
                    log_event("manager_fast_error", error=str(exc))
        time.sleep(30)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fast"
    if cmd == "--loop":
        loop()
    elif cmd == "fast":
        fast_cycle()
    elif cmd == "full":
        full_cycle()
    elif cmd == "resolve-dr":
        dr_id = sys.argv[2]
        opt = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        note = " ".join(sys.argv[5:]) if "--note" in sys.argv else ""
        try:
            resolve_dr(dr_id, opt, note)
        except ValueError as exc:
            print(f"❌ {exc}")
            raise SystemExit(1)
    else:
        print(__doc__)

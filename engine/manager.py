# -*- coding: utf-8 -*-
"""
Manager Loop v0.3 — منقول من معمارية v4.1.1 الخارجية مع تكييفها محليًا ومعالجة فجواتها.

الدورتان:
  fast (كل 15 دقيقة افتراضيًا): مسح حتمي لـ waiting_for فقط — انتقالات WAITING→OVERDUE،
      إدراج إجراء متابعة واحد لكل عنصر متأخر (idempotent ببصمة المحتوى)،
      طلبات قرار للمشاريع المتوقفة، انتهاء صلاحية الإجراءات المعتمدة.
  full (06:00 بتوقيت الرياض افتراضيًا): fast + توليد البريف واللوحة (chief_of_staff).

  python3 engine/manager.py fast
  python3 engine/manager.py full
  python3 engine/manager.py resolve-dr DR-001 --option 2 --note "السبب"
  python3 engine/manager.py --loop            (جدولة ذاتية بلا اعتماديات خارجية)

إضافاتنا على v4.1.1:
  - catch-up: لو فوّت النظام تشغيلة الصباح (جهاز نائم) تُنفَّذ فور الإقلاع.
  - تصعيد: طلب قرار تجاوز مهلته يُعلَّم «متأخر» في البريف ولا يختفي.
  - cooldown 7 أيام: لا يُعاد توليد طلب قرار لنفس المشروع بعد حله مباشرة.
  - write-on-change: الدورة السريعة لا تكتب في الحالة إلا إذا تغيّر شيء (لا فيضان تدقيق/نسخ).
"""
import datetime as dt
import hashlib
import json
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
MARKERS = os.path.join(BASE, "data", ".manager-markers.json")

now = lambda: dt.datetime.now(TZ)


def _hash(txt):
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def _as_date(x):
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x)[:10])


# ---------------------------------------------------------------- توحيد waiting_for إلى schema v2
def normalize_waiting(S):
    changed = False
    for i, w in enumerate(S["waiting_for"]):
        if w.get("schema_version") == 2:
            continue
        task = w.get("task") or w.get("item") or w.get("title") or f"عنصر انتظار {i + 1}"
        since = w.get("expected_by") or w.get("since") or w.get("expected_date") or now().date()
        S["waiting_for"][i] = {
            "schema_version": 2,
            "wid": "W-" + _hash(str(task))[:6],
            "task": task,
            "project_id": w.get("project_id"),
            "expected_from": w.get("expected_from", ""),
            "expected_by": since,
            "follow_up_draft": w.get("follow_up_draft"),
            "status": w.get("status") or "WAITING",
            "source": w.get("source", ""),
            # إبقاء الحقول القديمة للتوافق مع ما يُقرأ منها
            "item": task, "since": since,
        }
        changed = True
    return changed


# ---------------------------------------------------------------- الدورة السريعة (حتمية فقط)
def fast_cycle():
    store = Store()
    S = store.rows_all()
    changed = normalize_waiting(S)
    t = now()
    summary = {"overdue": 0, "actions": 0, "drs": 0, "superseded": 0, "expired": 0}

    # 1) انتقالات WAITING → OVERDUE + إجراء متابعة واحد لكل عنصر
    queue = S.get("action_queue", [])
    for w in S["waiting_for"]:
        if w.get("status") != "WAITING":
            continue
        due = w.get("expected_by")
        overdue = (_as_date(due) < t.date()) if due else False
        if not overdue:
            continue
        w["status"] = "OVERDUE"
        changed = True
        summary["overdue"] += 1
        draft = w.get("follow_up_draft") or f"السلام عليكم، أتابع بخصوص «{w['task']}» — هل من تحديث؟ (عبدالرحمن)"
        content = (f"متابعة متأخرة: {w['task']}\n"
                   f"كان متوقعًا من: {w.get('expected_from') or '—'} بحلول {_as_date(due).isoformat()}\n"
                   f"المسودة المقترحة:\n{draft}")
        h = _hash(content)
        if not any(a.get("content_hash") == h for a in queue):
            queue.append({
                "action_id": f"A-{len(queue) + 1:03d}", "type": "send_followup_message",
                "channel": "wa/email", "content": content, "content_hash": h,
                "status": "PENDING_APPROVAL", "created_at": t.date().isoformat(),
                "expires_at": (t.date() + dt.timedelta(days=2)).isoformat(),
                "approved_at": None, "executed_at": None})
            summary["actions"] += 1
            log_event("action_enqueued", action_id=queue[-1]["action_id"], hash=h, origin="manager_fast")

    # 2) انتهاء صلاحية إجراءات معلقة تقادمت
    for a in queue:
        if a["status"] == "PENDING_APPROVAL" and _as_date(a["expires_at"]) < t.date():
            a["status"] = "EXPIRED"
            changed = True
            summary["expired"] += 1

    # 2.5) مراجعات التعلّم: SCHEDULED → DUE (الإشعار ليس تعلماً — الدورة كاملة في learning_engine)
    for x in S.get("learning_reviews", []):
        if x["status"] == "SCHEDULED" and _as_date(x["due_date"]) <= t.date():
            x["status"] = "DUE"
            changed = True
            log_event("REVIEW_DUE", review=x["review_id"])

    # 3) طلبات قرار للمشاريع «النشطة المتوقفة فعليًا» (مع cooldown وتصعيد وسوبسيد)
    drs = S.get("decision_requests", [])
    stalled = [p for p in S["projects"]
               if p.get("الحالة") == "نشط" and (_as_date(p["آخر تقدم"]) < t.date() - dt.timedelta(days=STALLED_DAYS))]
    stalled_names = {p["المشروع"] for p in stalled}
    for dr in drs:
        if dr["status"] == "PENDING" and dr.get("project") and dr.get("project") not in stalled_names:
            dr["status"] = "SUPERSEDED"
            changed = True
            summary["superseded"] += 1
    for p in stalled:
        name = p["المشروع"]
        recent = [d for d in drs if d.get("project") == name and
                  (_as_date(d.get("resolved_at") or d.get("created_at")) >= t.date() - dt.timedelta(days=DR_COOLDOWN_DAYS))]
        pend = [d for d in drs if d.get("project") == name and d["status"] == "PENDING"]
        if recent or pend:
            continue
        drs.append({
            "id": f"DR-{len(drs) + 1:03d}", "project": name,
            "title": f"قرار مشروع متوقف: {name}",
            "context": f"حالته «نشط» لكن آخر تقدم قبل {(_as_date(p['آخر تقدم'])).isoformat()} "
                       f"({(t.date() - _as_date(p['آخر تقدم'])).days} يومًا)",
            "options": ["استئناف بخطوة واحدة محددة هذا الأسبوع", "تحويل الحالة إلى «متوقف»", "إغلاق وأرشفة"],
            "deadline": (t.date() + dt.timedelta(days=1)).isoformat(),
            "status": "PENDING", "created_at": t.date().isoformat(),
            "resolved_at": None, "resolution": None})
        changed = True
        summary["drs"] += 1
        log_event("decision_request_created", dr=drs[-1]["id"], project=name)

    if changed:
        S["action_queue"] = queue
        S["decision_requests"] = drs
        store.commit(S, "manager_fast", **summary)
        print(f"⚡ دورة سريعة: متأخر={summary['overdue']} | إجراءات جديدة={summary['actions']} | "
              f"طلبات قرار={summary['drs']} | منتهية={summary['expired']} | متجاوزة={summary['superseded']}")
    else:
        print("⚡ دورة سريعة: لا تغييرات (لا كتابة في الحالة — write-on-change)")
    return summary


# ---------------------------------------------------------------- الدورة الكاملة
def full_cycle():
    fast_cycle()
    r = subprocess.run([sys.executable, os.path.join(BASE, "engine", "chief_of_staff.py")],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)


# ---------------------------------------------------------------- حل طلب قرار → سجل القرارات
def resolve_dr(dr_id, option_no, note):
    store = Store()
    S = store.rows_all()
    dr = next((d for d in S.get("decision_requests", []) if d["id"] == dr_id and d["status"] == "PENDING"), None)
    if not dr:
        print(f"❌ لا يوجد طلب قرار مفتوح بالمعرف {dr_id}")
        sys.exit(1)
    try:
        choice = dr["options"][option_no - 1]
    except IndexError:
        print(f"❌ الخيار {option_no} غير موجود. المتاح: " + " / ".join(f"{i+1}) {o}" for i, o in enumerate(dr["options"])))
        sys.exit(1)
    dr["status"] = "RESOLVED"
    dr["resolved_at"] = now().date().isoformat()
    dr["resolution"] = choice
    if option_no == 2 and dr.get("project"):  # «تحويل إلى متوقف» → يُنفذ فعلًا في الحالة
        for p in S["projects"]:
            if p["المشروع"] == dr["project"]:
                p["الحالة"] = "متوقف"
                p["ملاحظات"] = (str(p.get("ملاحظات") or "") + f" | حُوّل إلى متوقف بقرار {dr['id']}").strip(" |")
    S["decisions"].append({
        "التاريخ": now().date(), "القرار": dr["title"], "البدائل المدروسة": " / ".join(dr["options"]),
        "الخيار": choice, "النتيجة المتوقعة": "", "تاريخ المراجعة": now().date() + dt.timedelta(days=30),
        "النتيجة الفعلية": None, "الحالة": "منفذ", "التقييم/الدرس": note or f"من طلب قرار {dr['id']}"})
    store.commit(S, "decision_resolved", dr=dr_id, option=choice[:40])
    log_event("decision_resolved", dr=dr_id, option_no=option_no)
    print(f"✅ {dr_id} → «{choice}» + سُجل في سجل القرارات (مراجعة بعد 30 يومًا)")


# ---------------------------------------------------------------- الجدولة الذاتية (اختيارية)
def _markers():
    try:
        return json.load(open(MARKERS, encoding="utf-8"))
    except Exception:
        return {}


def _save_markers(m):
    json.dump(m, open(MARKERS, "w", encoding="utf-8"), ensure_ascii=False)


def loop():
    print(f"🔁 حلقة المدير: سريع كل {FAST_INTERVAL // 60} دقيقة | كامل {MORNING_HOUR:02d}:{MORNING_MINUTE:02d} {TZ} | Ctrl+C للإيقاف")
    while True:
        t = now()
        m = _markers()
        if m.get("hb_day") != t.date().isoformat():  # نبض يومي — دليل أن الحلقة حية
            m["hb_day"] = t.date().isoformat()
            _save_markers(m)
            log_event("manager_loop_alive", tz=str(TZ))
        due_full = t.replace(hour=MORNING_HOUR, minute=MORNING_MINUTE, second=0, microsecond=0)
        if t >= due_full and m.get("last_full") != t.date().isoformat():
            try:
                full_cycle()
                m["last_full"] = t.date().isoformat()
                _save_markers(m)
            except Exception as e:
                log_event("manager_full_error", error=str(e))
        elif (not m.get("last_fast")) or (t - dt.datetime.fromisoformat(m["last_fast"])).total_seconds() >= FAST_INTERVAL:
            try:
                fast_cycle()
                m["last_fast"] = t.isoformat(timespec="seconds")
                _save_markers(m)
            except Exception as e:
                log_event("manager_fast_error", error=str(e))
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
        resolve_dr(dr_id, opt, note)
    else:
        print(__doc__)

# -*- coding: utf-8 -*-
"""التوقيت التلقائي (Automatic Timing) — v1.1.

يغلق الحلقة الأخيرة في v1.0: المحركات كانت تعمل فقط حين تُنادى (يدويًا أو من
`manager.py --loop` الذي لا يعمل على الخادم). هذا الملف يحوّلها إلى **جدولة
تلقائية** تعمل بسطر cron على أي خادم، أو بخيط داخل حاوية تشغيل بلا `cron`
(كالصورة الحالية على Railway).

الجدول الافتراضي (بتوقيت الرياض، قابل للضبط بالبيئة):

  ☀️ 06:30 يوميًا  ← بريف الصباح: دورة استباقية ثم بريف اليوم ثم دفعه للمحادثة
  🛰️ كل 3 ساعات   ← مسح دوري: دورة المدير السريعة + توزيع محرك الأتمتة + sweep
  📊 أحد 07:00     ← مراجعة الأسبوع الاستباقية (مع ضبط العتبات عند الطلب)

مبادئ صارمة مطابقة لبقية المحركات:
  • **لا أثر خارجي إطلاقًا** — كل ما يمس الخارج مسودة `PENDING_APPROVAL`
    في طابور الاعتماد؛ القناة الوحيدة المسموحة هنا هي رسالة نصية للمحادثة
    المالكة (نفس قناة تنبيهات `proactive`، وتُعطَّل بنفس المفتاح).
  • **idempotent + write-on-change**: كل تشغيل يُسجَّل في قسم `timing_runs`
    بمفتاح دورة (اليوم/الأسبوع) فلا يتكرر؛ الدورات التي لا تغيّر الحالة لا
    تكتبها أصلًا.
  • **catch-up آمن**: المعيار «الوقت مرّ ولم يُنفَّذ في هذه الدورة»، فإعادة
    التشغيل أو انقطاع الخادم لا يُفوّت البريف ولا يُكرّره.
  • **حماية من التراكب**: قفل عملية (`data/.timing.lock`) بـ non-blocking،
    فالنقرة التالية من cron تُنهي نفسها بهدوء إن كانت السابقة ما تزال تعمل.
  • **تراجع أمام الفشل**: وظيفة تفشل ← رجوع أُسّي (backoff) بدل إعادة محاولة
    كل دقيقة؛ الفشل موثَّق في التدقيق ولا يُسقط بقية الجدولة.

التشغيل من cron (التوصية — نبضة كل 5 دقائق والقرار للمحرّك؛ الغلاف يتولى
البيئة والمجلد والسجل logs/timing.log):
  */5 * * * * /path/to/repo/scripts/aios-timing.sh tick

أو بدقّة cron الأصلية مباشرة (بلا محاكاة — السطور توضع في نفس الملف):
  30 6 * * *   /path/to/repo/scripts/aios-timing.sh run brief
  15 */3 * * * /path/to/repo/scripts/aios-timing.sh run sweep
  0  7 * * 0   /path/to/repo/scripts/aios-timing.sh run review

على حاوية تشغيل بلا cron (Railway مثلًا): يعمل نفس الجدول افتراضيًا كخيط داخل
عملية الـ webhook (`connectors/timing_worker.py`)؛ لإيقاف الخيط وحده
`AIOS_TIMING_WORKER=0`، وللإيقاف الشامل للمحرّك `AIOS_TIMING_ENABLED=0`.

التشغيل من الطرفية (الأتمتة):
  python3 engine/timing.py list          ← الجدول + الحالة القادمة لكل وظيفة
  python3 engine/timing.py status        ← بطاقة JSON: آخر تشغيل + متى يستحق
  python3 engine/timing.py verify        ← برهان حياة كامل (13 بندًا + إصلاح) للمطوّر
  python3 engine/timing.py tick          ← نفّذ ما استحق الآن فقط
  python3 engine/timing.py run brief     ← تنفيذ وظيفة بعينها الآن (للاختبار)
  python3 engine/timing.py loop          ← مُنَبِّه مقيم داخل العملية (حاوية بلا cron)
  python3 engine/timing.py install-cron [--write]   ← توليد/تركيب سطور crontab

المتغيرات:
  AIOS_TIMING_ENABLED=0        ← إيقاف كامل (افتراضيًا مفعّل)
  TIMING_TICK_SECONDS=300      ← دورية نبض الوضع المقيم
  TIMING_BRIEF_AT=06:30  TIMING_BRIEF_ENABLED=1
  TIMING_SWEEP_INTERVAL_HOURS=3  TIMING_SWEEP_ENABLED=1
  TIMING_REVIEW_AT=07:00  TIMING_REVIEW_WEEKDAY=6  TIMING_REVIEW_ENABLED=1
  TIMING_REVIEW_DAYS=7  TIMING_REVIEW_APPLY=0
  TIMING_PUSH=1                ← دفع البريف/المراجعة لتيليجرام (0 = ملفات فقط)
  TIMING_RETRY_MINUTES=20      ← أرضية الرجوع عند الفشل
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

try:  # flock غير متوفر على ويندوز — هناك يُستخدم msvcrt بدلًا منه
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as _store_mod
from store import Store, log_event

TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
CRON_MARK = "AIOS-TIMING"   # وسم سطور crontab التي يولّدها المثبّت


def lock_path():
    """قفل التشغيل بجانب مخزن الحالة — يتبع AI_OS_DATA_DIR ليعمر عمره ويعمره."""
    return os.path.join(_store_mod.DATA_DIR, ".timing.lock")


AR_DAYS = {6: "الأحد", 0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء",
           3: "الخميس", 4: "الجمعة", 5: "السبت"}

now = lambda: dt.datetime.now(TZ)


# ---------------------------------------------------------------- الإعدادات
def _env_int(name, default):
    try:
        return int(str(os.environ.get(name, default)).strip())
    except ValueError:
        return default


def _env_flag(name, default=True):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip() != "0"


def _env_hhmm(name, default):
    raw = str(os.environ.get(name, default) or default).strip()
    return raw if re.match(r"^\d{1,2}:\d{2}$", raw) else default


def cfg():
    """إعدادات الجدولة — تُقرأ في كل نداء حتى تُطبق تغييرات البيئة فورًا."""
    return {
        "enabled": _env_flag("AIOS_TIMING_ENABLED", True),
        "tick_seconds": max(15, _env_int("TIMING_TICK_SECONDS", 300)),
        "push": _env_flag("TIMING_PUSH", True),
        "retry_minutes": max(1, _env_int("TIMING_RETRY_MINUTES", 20)),
        "jobs": {
            "brief": {"enabled": _env_flag("TIMING_BRIEF_ENABLED", True),
                      "time": _env_hhmm("TIMING_BRIEF_AT", "06:30")},
            "sweep": {"enabled": _env_flag("TIMING_SWEEP_ENABLED", True),
                      "interval_hours": max(1, _env_int("TIMING_SWEEP_INTERVAL_HOURS", 3))},
            "review": {"enabled": _env_flag("TIMING_REVIEW_ENABLED", True),
                       "time": _env_hhmm("TIMING_REVIEW_AT", "07:00"),
                       "weekday": _env_int("TIMING_REVIEW_WEEKDAY", 6) % 7,
                       "days": max(1, _env_int("TIMING_REVIEW_DAYS", 7)),
                       "apply": _env_flag("TIMING_REVIEW_APPLY", False)},
        },
    }


# جدول الوظائف — مصدر الحقيقة للجدولة التلقائية (نفس نمط scheduler.JOB_SPECS)
JOB_SPECS = [
    {"job_id": "timing.morning_brief", "handler": "brief", "emoji": "☀️",
     "name": "بريف الصباح الاستباقي (دورة + ملف + دفع للجوال)",
     "cadence": "daily", "kind": "brief",
     "purpose": "sweep ثم reports/proactive-brief-YYYY-MM-DD.md ثم رسالة الصباح"},
    {"job_id": "timing.periodic_sweep", "handler": "sweep", "emoji": "🛰️",
     "name": "المسح الدوري: دورة المدير السريعة + محرك الأتمتة + الاستباقية",
     "cadence": "interval", "kind": "sweep",
     "purpose": "متأخرات/انتهاء صلاحيات + مسودات الجدولة + حلقة استباقية"},
    {"job_id": "timing.weekly_review", "handler": "review", "emoji": "📊",
     "name": "مراجعة الأسبوع الاستباقية (وقبولك/تراجعك من الواقع)",
     "cadence": "weekly", "kind": "review",
     "purpose": "تقرير review + ضبط العتبات اختياريًا + دفعه للجوال"},
]

JOB_ALIASES = {"brief": "timing.morning_brief", "sweep": "timing.periodic_sweep",
               "review": "timing.weekly_review",
               "timing.morning_brief": "timing.morning_brief",
               "timing.periodic_sweep": "timing.periodic_sweep",
               "timing.weekly_review": "timing.weekly_review"}


def jobs_for(cfg_dict=None):
    """الوظائف المفعّلة، بدمج إعدادات البيئة على كل وظيفة."""
    c = cfg_dict or cfg()
    out = []
    for spec in JOB_SPECS:
        job = dict(spec)
        job.update(c["jobs"].get(spec["kind"], {}))
        job["due"] = job.pop("enabled", True)
        out.append(job)
    return out


def job_by_name(name, cfg_dict=None):
    key = JOB_ALIASES.get(str(name or "").strip())
    if not key:
        raise ValueError(f"وظيفة غير معروفة: {name} — المتاحة: brief|sweep|review")
    for job in jobs_for(cfg_dict):
        if job["job_id"] == key:
            return job
    raise ValueError(f"الوظيفة معطّلة بالبيئة: {key}")


# ---------------------------------------------------------------- أدوات زمنية
def _hhmm(s):
    h, m = str(s).split(":")
    return dt.time(int(h), int(m))


def sun_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def cycle_key(job, ref: dt.datetime) -> str:
    """مفتاح الدورة — ما يمنع التكرار داخل اليوم/الأسبوع نفسه."""
    d = ref.date()
    if job["cadence"] == "daily":
        return d.isoformat()
    if job["cadence"] == "weekly":
        return sun_of(d).isoformat()
    return d.isoformat()  # interval: يُستخدم فقط لأرشيف القراءة


def _as_dt(x):
    if isinstance(x, dt.datetime):
        return x if x.tzinfo else x.replace(tzinfo=TZ)
    if not x:
        return None
    try:
        val = dt.datetime.fromisoformat(str(x).replace("T", " ")[:19])
    except ValueError:
        return None
    return val if val.tzinfo else val.replace(tzinfo=TZ)


def next_due_label(job, ref: dt.datetime) -> str:
    """وصف إنساني للموعد القادم (للبطاقات والـ status)."""
    if job["cadence"] == "interval":
        return f"كل {job['interval_hours']} س"
    t = _hhmm(job["time"])
    if job["cadence"] == "weekly":
        days = (job["weekday"] - ref.weekday()) % 7
        if days == 0 and ref.time() >= t:
            days = 7
    else:
        days = 0 if ref.time() < t else 1
    when = (ref + dt.timedelta(days=days)).date()
    return f"{AR_DAYS[when.weekday()]} {when.isoformat()} {t:%H:%M}"


def due_info(job, ref: dt.datetime, runs, c):
    """تعيد (due, reason) لوظيفة عند لحظة معينة — دالة نقية بلا كتابة."""
    if not job.get("due"):
        return False, "معطّلة بالبيئة"
    hist = [r for r in runs if str(r.get("job_id")) == job["job_id"]]
    hist.sort(key=lambda r: str(r.get("finished_at") or r.get("started_at") or ""))
    last_ok = next((r for r in reversed(hist) if r.get("status") == "ok"), None)
    last = hist[-1] if hist else None
    if last and last.get("status") == "error":
        fails = 0
        for r in reversed(hist):
            if r.get("status") != "error":
                break
            fails += 1
        backoff = c["retry_minutes"] * (2 ** min(max(fails - 1, 0), 6))
        retry_at = _as_dt(last.get("finished_at")) or ref
        waited = (ref - retry_at).total_seconds() / 60.0
        if waited < backoff:
            return False, f"فشل سابق — رجوع {int(backoff - waited)} د"
    if job["cadence"] == "interval":
        gap = dt.timedelta(hours=int(job["interval_hours"]))
        if last_ok is None:
            return True, "لم تُنفَّذ بعد"
        prev = _as_dt(last_ok.get("finished_at")) or ref
        elapsed = (ref - prev).total_seconds() / 3600
        if elapsed >= job["interval_hours"]:
            return True, f"مرّت {elapsed:.1f} س من أصل {job['interval_hours']}"
        return False, f"القادم بعد {int((gap - (ref - prev)).total_seconds() // 60)} د"
    t = _hhmm(job["time"])
    if job["cadence"] == "weekly" and ref.weekday() != int(job["weekday"]) % 7:
        return False, "ليس يومها"
    if ref.time() < t:
        return False, f"لم يحن {job['time']} بعد"
    if last_ok is not None and str(last_ok.get("cycle_key")) == cycle_key(job, ref):
        return False, "نُفِّذت في هذه الدورة"
    return True, f"مستحقة منذ {job['time']}"


def due_jobs(ref=None, store=None, c=None):
    """كل الوظائف المستحقة عند `ref` — [(job, reason)]، بلا أي تنفيذ."""
    c = c or cfg()
    ref = ref or now()
    runs = _runs(store or Store())
    out = []
    for job in jobs_for(c):
        due, reason = due_info(job, ref, runs, c)
        if due:
            out.append((job, reason))
    return out


def _runs(store):
    return list(store.rows_all().get("timing_runs", []))


# ---------------------------------------------------------------- قفل التشغيل
def _lock_handle(path, blocking, wait_seconds=30.0):
    """يحاول اقتناص قفل حصري على الملف. يعيد المقبض، أو None إن مشغول.

    لا قفل على أنظمة بلا fcntl/msvcrt: نعيد المقبض بلا قفل (أفضل جهد) بدل أن
    تتعطل الجدولة كلها — الحماية المتبقية هي علامات Idempotency في الحالة.
    """
    with open(path, "ab"):
        pass  # يضمن وجود الملف قبل محاولة القفل على كل المنصات
    if os.name == "nt":  # pragma: no cover - مسار ويندوز
        try:
            import msvcrt
        except ImportError:
            return open(path, "rb")
        handle = open(path, "r+b")
        deadline = time.time() + wait_seconds
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return handle
            except OSError:
                if not blocking or time.time() >= deadline:
                    handle.close()
                    return None
                time.sleep(0.5)
    if fcntl is None:  # pragma: no cover - أنظمة بلا flock
        return open(path, "rb")
    handle = open(path, "a+b")
    deadline = time.time() + wait_seconds
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if not blocking or time.time() >= deadline:
                handle.close()
                return None
            time.sleep(0.5)


def _unlock_handle(handle):
    if handle is None:
        return
    try:
        if os.name == "nt":  # pragma: no cover - مسار ويندوز
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


@contextlib.contextmanager
def run_lock(path=None, blocking=False):
    """قفل عملية واحد للجدولة — يمنع تراكب نسخ cron المتتالية.

    يعيد True إن أُخذ القفل و False إن كانت دورة أخرى تعمل الآن. في وضع cron
    (blocking=False) يُفضَّل الانسحاب بهدوء على الانتظار؛ ولمن يريد الانتظار
    (تشغيل يدوي/اختبار) blocking=True مع سقف 30 ثانية.
    """
    path = path or lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = _lock_handle(path, blocking)
    try:
        yield handle is not None
    finally:
        _unlock_handle(handle)


# ---------------------------------------------------------------- قناة الجوال
def push(text, chat_id=None, token=None):
    """رسالة للمحادثة المالكة عبر قناة تنبيهات الاستباقية نفسها — بلا شبكة إن لا قناة."""
    try:
        import proactive
    except Exception as exc:  # noqa: BLE001
        return False, f"proactive_unavailable: {str(exc)[:120]}"
    if proactive._push_disabled() or not cfg()["push"]:
        return False, "disabled_env"
    status = proactive.telegram_push_status()
    if status != "ready":
        return False, status
    try:
        ok = proactive._telegram_send(text, chat_id=chat_id, token=token)
    except Exception as exc:  # noqa: BLE001 — الفشل موثَّق ولا يُسقط الوظيفة
        log_event("timing_push_error", error=str(exc)[:200])
        return False, f"telegram_error: {str(exc)[:120]}"
    return (True, "sent") if ok else (False, "no_channel")


def _soft(module_name):
    try:
        return __import__(module_name)
    except Exception as exc:  # noqa: BLE001
        log_event("timing_import_error", module=module_name, error=str(exc)[:200])
        return None


# ---------------------------------------------------------------- المنفِّذات
def run_brief(store=None, ref=None, c=None, push_enabled=None):
    """☀️ بريف الصباح: دورة استباقية ← ملف البريف ← رسالة للمحادثة المالكة."""
    t = ref or now()
    c = c or cfg()
    store = store or Store()
    out = {"steps": {}, "detail": {}}
    proactive = _soft("proactive")
    if proactive is None:
        return False, "محرك الاستباقية غير قابل للاستيراد"
    if proactive.enabled():
        out["steps"]["sweep"] = dict(proactive.sweep(store=store, now_dt=t, verbose=False))
        out["detail"]["sweep"] = {k: out["steps"]["sweep"].get(k) for k in
                                  ("act", "prepare", "alert", "batched", "suggest", "missed")}
    else:
        out["steps"]["sweep"] = {"disabled": True}
    path = proactive.render_brief(store=store, now_dt=t)
    out["steps"]["brief"] = os.path.relpath(path, BASE)
    text = morning_brief_text(store=store, ref=t)
    send = cfg()["push"] if push_enabled is None else push_enabled
    ok, why = (push(text) if send else (False, "push_disabled"))
    out["steps"]["push"] = why
    return True, {"summary": out["detail"].get("sweep", {}), "brief": out["steps"]["brief"],
                  "push": "sent" if ok else why, "text": text}


def run_sweep(store=None, ref=None, c=None, **_kw):
    """🛰️ المسح الدوري: صيانة حتمية للحالة ← مسودات محرك الأتمتة ← حلقة الاستباقية."""
    t = ref or now()
    store = store or Store()
    detail = {}
    manager = _soft("manager")
    if manager is not None:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fast = manager.fast_cycle()
            detail["fast"] = {k: v for k, v in dict(fast).items() if v}
        except Exception as exc:  # noqa: BLE001
            detail["fast_error"] = str(exc)[:160]
    scheduler = _soft("scheduler")
    if scheduler is not None:
        try:
            produced, skipped = scheduler.dispatch_due(ref=t, store=store, verbose=False)
            detail["scheduler"] = {"produced": produced, "nothing_new": skipped}
        except Exception as exc:  # noqa: BLE001
            detail["scheduler_error"] = str(exc)[:160]
    proactive = _soft("proactive")
    if proactive is not None and proactive.enabled():
        try:
            s = proactive.sweep(store=store, now_dt=t, verbose=False)
            detail["proactive"] = {k: s.get(k) for k in
                                   ("act", "prepare", "alert", "batched", "suggest",
                                    "missed", "pushed", "loops_open")}
        except Exception as exc:  # noqa: BLE001
            detail["proactive_error"] = str(exc)[:160]
    ok = not any(k.endswith("_error") for k in detail)
    return ok, detail


def run_review(store=None, ref=None, c=None, push_enabled=None):
    """📊 مراجعة الأسبوع: تقرير + (اختياريًا) ضبط العتبات + دفعه للجوال."""
    t = ref or now()
    c = c or cfg()
    store = store or Store()
    proactive = _soft("proactive")
    if proactive is None:
        return False, "محرك الاستباقية غير قابل للاستيراد"
    days = int(c["jobs"]["review"]["days"])
    text = proactive.review_text(store=store, days=days, today=t.date())
    applied = None
    if c["jobs"]["review"]["apply"]:
        try:
            rep = proactive.acceptance_report(store=store, days=days, today=t.date())
            recs, _notes = proactive.tuning_recommendations(rep, proactive.resolve_cfg(store))
            applied = proactive.apply_tuning(recs, store=store) or None
        except Exception as exc:  # noqa: BLE001
            applied = f"error: {str(exc)[:120]}"
    send = cfg()["push"] if push_enabled is None else push_enabled
    ok, why = (push(text) if send else (False, "push_disabled"))   # نص المراجعة يبدأ بـ 📊
    head = text.splitlines()[0] if text else ""
    return True, {"head": head, "days": days, "applied": applied or "—",
                  "push": "sent" if ok else why, "text": text}


HANDLERS = {"brief": run_brief, "sweep": run_sweep, "review": run_review}


# ---------------------------------------------------------------- نص بريف الصباح
def morning_brief_text(store=None, ref=None):
    """رسالة الصباح المختصرة من الحالة فقط — بلا شبكة ولا حسابات ثقيلة."""
    t = ref or now()
    store = store or Store()
    S = store.rows_all()
    today = t.date().isoformat()
    rows = [a for a in S.get("proactive_actions", []) if str(a.get("ts", ""))[:10] == today]
    acts = [a for a in rows if a.get("decision") == "ACT"]
    preps = [a for a in rows if a.get("decision") in ("PREPARE", "ALERT_DRAFT")]
    alerts = [a for a in rows if a.get("decision") in ("ALERT", "ALERT_DRAFT")]
    pending = [q for q in S.get("action_queue", [])
               if q.get("status") == "PENDING_APPROVAL"]
    open_loops = [l for l in S.get("open_loops", []) if l.get("status") == "OPEN"]
    missed = [l for l in S.get("open_loops", [])
              if l.get("status") in ("MISSED", "RECOVERING")]
    d = t.date()
    lines = [f"☀️ بريف الصباح الاستباقي — {AR_DAYS[d.weekday()]} {d.isoformat()}",
             f"نُفّذ {len(acts)} · جُهّز {len(preps)} · تنبيه {len(alerts)} · "
             f"حلقات مفتوحة {len(open_loops)} · فائت {len(missed)}"]
    top = sorted(alerts + preps, key=lambda a: -float(a.get("points") or 0))[:3]
    for i, a in enumerate(top, 1):
        lines.append(f"{i}. {a.get('title')}"[:180])
    if not top:
        lines.append("لا ما يستوقظك اليوم — كل الحلقات تحت السيطرة ✅")
    if pending:
        lines.append(f"✋ {len(pending)} مسودة بانتظار اعتمادك: /approve")
    lines += [f"🗂 reports/proactive-brief-{today}.md",
              "الحالة: /proactive · التوقيت: /timing"]
    return "\n".join(lines)


# ---------------------------------------------------------------- تسجيل التشغيل
def _record(store, job, ref, status, detail, started):
    def mutate(S):
        runs = list(S.get("timing_runs", []))
        runs.append({
            "run_id": f"TR-{len(runs) + 1:04d}",
            "job_id": job["job_id"],
            "cycle_key": cycle_key(job, ref),
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": ref.isoformat(timespec="seconds"),
            "duration_s": max(0.0, round((ref - started).total_seconds(), 2)),
            "status": status,
            "trigger": job.get("trigger", "tick"),
            "detail": json.dumps({k: v for k, v in dict(detail).items() if k != "text"},
                                 ensure_ascii=False, default=str)[:900],
        })
        S["timing_runs"] = runs[-400:]
        markers = dict(S.get("manager_markers") or {})
        day = ref.date().isoformat()
        if markers.get("timing_heartbeat_day") != day:
            markers["timing_heartbeat_day"] = day
            markers["timing_heartbeat_at"] = ref.isoformat(timespec="seconds")
            S["manager_markers"] = markers
        return True, None
    store.transaction(mutate, "timing_run", job=job["job_id"], status=status)
    log_event("timing_run", job=job["job_id"], status=status,
              trigger=job.get("trigger", "tick"),
              detail=json.dumps(detail, ensure_ascii=False, default=str)[:300])


def _execute(job, store=None, ref=None, verbose=True):
    """ينفّذ كائن وظيفة معزولًا: الوظيفة تفشل ولا تُسقط بقية الجدولة."""
    c = cfg()
    store = store or Store()
    t = ref or now()
    try:
        ok, detail = HANDLERS[job["handler"]](store=store, ref=t, c=c)
        status = "ok" if ok else "error"
    except Exception as exc:  # noqa: BLE001
        status, detail = "error", {"error": str(exc)[:240]}
    if status == "error":
        log_event("timing_job_error", job=job["job_id"],
                  error=str(detail.get("error") or detail)[:240])
    _record(store, job, now(), status, detail, t)
    if verbose:
        body = json.dumps({k: v for k, v in detail.items() if k != "text"},
                          ensure_ascii=False, default=str)
        reason = f" (سبب: {job['reason']})" if job.get("reason") else ""
        print(f"{job['emoji']} {job['job_id']} → {status}: {body[:500]}{reason}")
    return {"job_id": job["job_id"], "status": status, "detail": detail}


def run_job(name, force=False, store=None, ref=None, verbose=True, trigger="cli"):
    """تنفيذ وظيفة واحدة باسمها/اختصارها مع تسجيلها في دفتر التشغيل."""
    c = cfg()
    job = job_by_name(name, c)
    if not job.get("due"):
        if not force:
            if verbose:
                print(f"⏸️ {job['job_id']} معطّلة بالبيئة — مرّر force للتشغيل رغم ذلك.")
            return {"job_id": job["job_id"], "status": "disabled", "detail": {}}
        if verbose:
            print(f"⚠️ {job['job_id']} معطّلة بالبيئة لكنك أمرت بتشغيلها صراحةً — "
                  "الجدولة التلقائية لا تزال تتجاهلها.")
    return _execute(dict(job, trigger=trigger, reason=("force" if force else None)),
                    store=store, ref=ref, verbose=verbose)


def _tick_locked(store, t, c, verbose, trigger):
    pending = due_jobs(t, store, c)
    if not pending:
        if verbose:
            print(f"⏰ لا وظيفة مستحقة عند {t:%H:%M} ({TZ}) — نبض بلا كتابة.")
        return {"status": "idle", "ran": [], "at": t.isoformat(timespec="seconds")}
    ran = []
    for job, reason in pending:
        res = _execute(dict(job, trigger=trigger, reason=reason),
                       store=store, ref=now(), verbose=verbose)
        res["reason"] = reason
        ran.append(res)
    return {"status": "ran", "ran": ran, "at": t.isoformat(timespec="seconds")}


def tick(store=None, ref=None, verbose=True, trigger="cron"):
    """نفّذ كل المستحق الآن — النداء الذي يوضع في cron. آمن التكرار والتراكب."""
    c = cfg()
    if not c["enabled"]:
        if verbose:
            print("⏸️ التوقيت التلقائي معطّل (AIOS_TIMING_ENABLED=0)")
        return {"status": "disabled", "ran": []}
    store = store or Store()
    t = ref or now()
    try:
        with run_lock(blocking=False) as acquired:
            if not acquired:
                if verbose:
                    print("🔒 دورة توقيت أخرى تعمل الآن — تجاوز هذه النقرة.")
                return {"status": "busy", "ran": []}
            return _tick_locked(store, t, c, verbose, trigger)
    except Exception as exc:  # noqa: BLE001 — عطب القفل لا يوقف الجدولة أبدًا
        # البقية محميّة بمفاتيح الدورة + write-on-change، فمتابعة بلا قفل آمنة
        log_event("timing_lock_error", error=str(exc)[:200])
        print(f"⚠️ تعذّر القفل ({str(exc)[:120]}) — متابعة بلا ضمان ضد التراكب.", flush=True)
        return _tick_locked(store, t, c, verbose, trigger)


def loop(stop_event=None, sleep_seconds=None):
    """مُنَبِّه مقيم للتشغيل داخل حاوية بلا cron — نفس منطق tick بنبض دوري."""
    import threading
    stop_event = stop_event or threading.Event()
    interval = float(sleep_seconds if sleep_seconds is not None else cfg()["tick_seconds"])
    print(f"🕰️ التوقيت التلقائي (مقيم): نبض كل {int(interval)} ث · {TZ}", flush=True)
    while not stop_event.is_set():
        try:
            tick(verbose=True, trigger="loop")
        except Exception as exc:  # noqa: BLE001
            log_event("timing_loop_error", error=str(exc)[:240])
            print(f"timing loop warning: {str(exc)[:220]}", flush=True)
        if stop_event.wait(max(5.0, interval)):
            break


# ---------------------------------------------------------------- الحالة
def timing_status(store=None, ref=None):
    c = cfg()
    t = ref or now()
    store = store or Store()
    S = store.rows_all()
    runs = list(S.get("timing_runs", []))
    jobs = []
    for job in jobs_for(c):
        due, reason = due_info(job, t, runs, c)
        hist = [r for r in runs if str(r.get("job_id")) == job["job_id"]]
        last = hist[-1] if hist else None
        jobs.append({
            "job_id": job["job_id"], "emoji": job["emoji"], "name": job["name"],
            "cadence": job["cadence"], "enabled": bool(job.get("due")),
            "when": (f"كل {job['interval_hours']} س" if job["cadence"] == "interval"
                     else f"{job['time']}" + (" — " + AR_DAYS[int(job['weekday']) % 7]
                                             if job["cadence"] == "weekly" else "")),
            "due_now": due, "reason": reason, "next": next_due_label(job, t),
            "last_run": (last or {}).get("finished_at"), "last_status": (last or {}).get("status"),
            "last_detail": (last or {}).get("detail"),
        })
    push_state = "unknown"
    try:
        import proactive
        push_state = proactive.telegram_push_status()
    except Exception as exc:  # noqa: BLE001
        push_state = f"unavailable: {str(exc)[:80]}"
    markers = S.get("manager_markers") or {}
    return {
        "enabled": c["enabled"], "timezone": str(TZ), "tz_time": t.isoformat(timespec="minutes"),
        "tick_seconds": c["tick_seconds"], "push": c["push"], "push_channel": push_state,
        "heartbeat_day": markers.get("timing_heartbeat_day"),
        "heartbeat_at": markers.get("timing_heartbeat_at"),
        "runs_recorded": len(runs),
        "next_line": {
            "brief": f"{c['jobs']['brief']['time']} يوميًا",
            "sweep": f"كل {c['jobs']['sweep']['interval_hours']} ساعات",
            "review": f"{AR_DAYS[c['jobs']['review']['weekday']]} "
                      f"{c['jobs']['review']['time']}",
        },
        "jobs": jobs,
        "last_runs": [{k: r.get(k) for k in
                       ("job_id", "finished_at", "status", "trigger", "detail")}
                      for r in runs[-6:]][::-1],
    }


def verify(store=None, ref=None):
    """برهان حياة واحد للجدولة التلقائية — يُطبع للمطوّر أو يُلصق كما هو في الرد.

    يفحص الطبقات التي لا تظهر في مخرجات الوظيفة نفسها: أعلام البيئة، ساعة
    الخادم مقابل منطقة الجدولة، نبض اليوم في الحالة، دفتر timing_runs، أخطاء
    اليوم، قناة تيليجرام، ملف بريف اليوم، وجود سطر cron/وحدة timer، قابلية
    الكتابة لمجلد البيانات، وتوفر القفل الآن.
    """
    c = cfg()
    t = ref or now()
    store = store or Store()
    S = store.rows_all()
    today = t.date().isoformat()
    checks = []

    def add(cid, label, state, value, fix=""):
        checks.append({"id": cid, "label": label, "state": state, "value": value,
                       "fix": fix})

    add("engine", "محرّك الجدولة (AIOS_TIMING_ENABLED)",
        "ok" if c["enabled"] else "fail", f"enabled={c['enabled']} · worker-loop={c['tick_seconds']}s",
        "" if c["enabled"] else "AIOS_TIMING_ENABLED=0 — الجدولة موقوفة بالبيئة")
    add("worker", "خيط الحاوية (AIOS_TIMING_WORKER)",
        "ok" if os.environ.get("AIOS_TIMING_WORKER", "1").strip() != "0" else "warn",
        os.environ.get("AIOS_TIMING_WORKER", "1 (default)"),
        "على Railway/X1: الخيط هو بديل cron؛ فعّله أو اضبط سطر cron")
    note = _server_tz_note()
    add("timezone", f"منطقة الجدولة = {TZ}", "warn" if note else "ok",
        (note or "ساعة الخادم مطابقة لمنطقة الجدولة"),
        "النبضة كل 5 دقائق تتجاهل فروق الساعة؛ سطور native تحتاج توقيت الخادم" if note else "")
    add("schedule", "الجدول الفاعل", "ok",
        f"brief={c['jobs']['brief']['time']} · sweep=every {c['jobs']['sweep']['interval_hours']}h · "
        f"review={AR_DAYS[c['jobs']['review']['weekday']]} {c['jobs']['review']['time']}",
        "")
    markers = S.get("manager_markers") or {}
    hb = str(markers.get("timing_heartbeat_day") or "")
    runs = list(S.get("timing_runs", []))
    runs_today = [r for r in runs if str(r.get("finished_at", ""))[:10] == today]
    errs_today = [r for r in runs_today if r.get("status") != "ok"]
    pending_now = due_jobs(t, store, c)
    # «لا شيء اليوم» عطلٌ فقط إذا كان هناك ما يستحق — وإلا فإعداد أو هدولة منتظرة
    pulse_state = "ok" if hb == today else ("fail" if pending_now else "warn")
    add("heartbeat", "نبض اليوم في الحالة", pulse_state,
        hb or ("لا نبض ولا شيء مستحق الآن" if not pending_now else "لا يوجد"),
        "لم تُنفَّذ أي دورة مع وجود وظيفة مستحقة: `crontab -l | grep AIOS-TIMING` و tail -n 40 logs/timing.log")
    add("runs", "دفتر التشغيل اليوم (timing_runs)",
        "ok" if runs_today else ("fail" if pending_now else "warn"),
        f"{len(runs_today)} تشغيل ({len({r.get('job_id') for r in runs_today})}/{len(jobs_for(c))} وظائف)"
        + ("" if pending_now else " · لا مستحق الآن"),
        "python3 engine/timing.py tick — أو تحقق من نبض cron")
    add("errors", "أخطاء اليوم", "fail" if len(errs_today) >= 3 else
        ("warn" if errs_today else "ok"),
        f"{len(errs_today)}",
        "راجع data/audit.jsonl: grep timing_job_error")
    channel = "unknown"
    try:
        import proactive
        channel = proactive.telegram_push_status()
    except Exception as exc:  # noqa: BLE001
        channel = f"unavailable: {str(exc)[:60]}"
    add("push", "قناة رسالة الصباح/المراجعة (تيليجرام)",
        "ok" if channel == "ready" else "warn", f"{channel} · TIMING_PUSH={1 if c['push'] else 0}",
        "الملفات تُولَّد بلا قناة؛ اضبط TELEGRAM_BOT_TOKEN و TELEGRAM_ALLOWED_CHAT_ID")
    brief_file = os.path.join(BASE, "reports", f"proactive-brief-{today}.md")
    add("brief_file", "ملف بريف اليوم", "ok" if os.path.exists(brief_file) else "warn",
        os.path.relpath(brief_file, BASE), "python3 engine/proactive.py brief")
    cron_state, cron_value = "warn", "غير متوفر على هذا النظام"
    if os.path.exists(os.path.join(os.path.expanduser("~"), ".config", "systemd", "user",
                                   "aios-timing.timer")):
        cron_state, cron_value = "ok", "systemd user timer: aios-timing.timer"
    else:
        try:
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            if res.returncode == 0:
                hit = [ln.strip() for ln in res.stdout.splitlines() if CRON_MARK in ln]
                cron_state = "ok" if hit else "warn"
                cron_value = "\n      ".join(hit) if hit else "لا سطر " + CRON_MARK + " في crontab"
        except FileNotFoundError:
            cron_value = "لا crontab (حاوية؟) — استخدم خيط الحاوية أو systemd timer"
    add("installer", "تثبيت الجدولة (cron / timer)", cron_state, cron_value,
        "bash autostart/cron/install.sh")
    try:
        data_dir = os.path.dirname(store.path)
        os.makedirs(data_dir, exist_ok=True)   # مجلد جديد ليس عطلًا — الحالة ستنشئه عند أول كتابة
        probe = os.path.join(data_dir, ".timing.verify")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(today)
        os.remove(probe)
        add("data_dir", f"مجلد البيانات قابل للكتابة ({os.path.dirname(store.path)})", "ok",
            "rw", "")
    except Exception as exc:  # noqa: BLE001
        add("data_dir", "مجلد البيانات قابل للكتابة", "fail", str(exc)[:120],
            "اضبط AI_OS_DATA_DIR على مجلد قابل للكتابة (Volume على Railway)")
    try:
        with run_lock(blocking=False) as acquired:
            add("lock", "قفل التوقيت متاح الآن", "ok" if acquired else "warn",
                "متاح" if acquired else "دورة أخرى تعمل الآن",
                "عادي أثناء تشغيل طويل؛ تحقق إن استمر أكثر من 10 دقائق")
    except Exception as exc:  # noqa: BLE001
        add("lock", "قفل التوقيت", "warn", f"تعذر القفل: {str(exc)[:80]}", "")
    add("state_schema", "قسم timing_runs في مخزن الحالة",
        "ok" if "timing_runs" in S else "fail", f"{len(runs)} صف",
        "النشر الحالي أقدم من v1.1 — ادمج PR التوقيت وأعد البناء")
    states = [k["state"] for k in checks]
    verdict = "fail" if "fail" in states else ("warn" if "warn" in states else "ok")
    return {
        "verdict": verdict,
        "at": t.isoformat(timespec="seconds"),
        "timezone": str(TZ),
        "summary": (f"{states.count('ok')}/{len(states)} فحص نظيف · "
                    f"أخطاء اليوم {len(errs_today)} · قناة {channel}"),
        "checks": checks,
        "last_runs": [{k: r.get(k) for k in ("job_id", "finished_at", "status", "trigger")}
                      for r in runs[-5:]][::-1],
    }


def verify_text(store=None, ref=None):
    """نسخة نصية من verify() — للّصق في رد المطوّر أو لمراجعة سريعة."""
    v = verify(store, ref)
    icons = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    lines = [f"🕰️ تحقق التوقيت التلقائي — {v['at']} · {v['timezone']}",
             f"الحكم: {'✅ يعمل' if v['verdict'] == 'ok' else ('⚠️ يعمل مع ملاحظات' if v['verdict'] == 'warn' else '❌ لا يعمل')}"
             f" — {v['summary']}", ""]
    for k in v["checks"]:
        lines.append(f"{icons[k['state']]} {k['label']}")
        for part in str(k["value"]).splitlines():
            if part.strip():
                lines.append(f"      {part.strip()}")
        if k["fix"] and k["state"] != "ok":      # الإصلاح يُعرض حيث يلزم لا تحت كل سطر نظيف
            lines.append(f"      ↳ {k['fix']}")
    if v["last_runs"]:
        lines += ["", "آخر التشغيلات:"]
        for r in v["last_runs"]:
            lines.append(f"  • {r['job_id']} — {r['status']} @ {r['finished_at']} "
                         f"({r.get('trigger', '—')})")
    return "\n".join(lines)


def status_text(store=None, ref=None):
    """بطاقة نصية مختصرة لبوت تيليجرام (/timing)."""
    st = timing_status(store, ref)
    lines = ["🕰️ التوقيت التلقائي (cron)",
             f"الحالة: {'▶️ فعّال' if st['enabled'] else '⏸️ معطّل'} · "
             f"{st['timezone']} · الآن {st['tz_time'][11:16]}",
             f"قناة الرسائل: {st['push_channel']} · "
             f"نبض الوضع المقيم: {st['tick_seconds']} ث"]
    icons = {"ok": "✅", "error": "❌", "skipped": "⏭️", None: "▫️"}
    for j in st["jobs"]:
        state = "🟢 مستحقة الآن" if j["due_now"] else "⏳"
        lines.append(f"{j['emoji']} {j['when']:<22} {state} · القادم {j['next']}")
        last = f"آخر تشغيل: {j['last_run']}" if j["last_run"] else "لم تُنفَّذ بعد"
        lines.append(f"    {icons.get(j['last_status'], '▫️')} {last}"
                     + (f" ({j['last_status']})" if j["last_status"] else ""))
    lines.append("من الطرفية: python3 engine/timing.py verify · من الجوال: "
                 "/timing_run [brief|sweep|review]")
    return "\n".join(lines)


# ---------------------------------------------------------------- سطور cron
def crontab_lines(repo=None, python=None, mode="tick"):
    """توليد سطور crontab الجاهزة للّصق (مع وسم يمكن إزالة/تحديث السطور به)."""
    repo = os.path.abspath(repo or BASE)
    py = python or sys.executable or "/usr/bin/python3"
    c = cfg()
    head = (f"# {CRON_MARK} — Abdulrahman AI OS التوقيت التلقائي "
            f"(لا تُحرّر هذا السطر: يحدّده installer)")
    wrapper = f"{repo}/scripts/aios-timing.sh"
    if mode == "tick":
        # الغلاف يكتب في logs/timing.log بنفسه — بلا إعادة توجيه في سطر cron
        return "\n".join([
            head,
            f"*/5 * * * * {wrapper} tick  # {CRON_MARK}",
            f"@reboot sleep 30 && {wrapper} tick  # {CRON_MARK}",
        ])
    lines = [head]
    if c["jobs"]["brief"]["enabled"]:
        h, m = c["jobs"]["brief"]["time"].split(":")
        lines.append(f"{int(m)} {int(h)} * * * {wrapper} run brief  # {CRON_MARK}")
    if c["jobs"]["sweep"]["enabled"]:
        lines.append(f"15 */{c['jobs']['sweep']['interval_hours']} * * * "
                     f"{wrapper} run sweep  # {CRON_MARK}")
    if c["jobs"]["review"]["enabled"]:
        rh, rm = c["jobs"]["review"]["time"].split(":")
        lines.append(f"{int(rm)} {int(rh)} * * {c['jobs']['review']['weekday']} "
                     f"{wrapper} run review  # {CRON_MARK}")
    del py  # وضع native يمر عبر الغلاف كي تبقى البيئة والسجل في مكانهما
    offset = _server_tz_note()
    if offset:
        lines.insert(1, f"# ⚠️ cron يعتمد ساعة الخادم: {offset}")
    return "\n".join(lines)


def _server_tz_note():
    """تنبيه إن اختلفت ساعة الخادم عن منطقة الجدولة (السطر «30 6» ليس 06:30 الرياض)."""
    try:
        server = dt.datetime.now().astimezone()
        local = now()
    except Exception:  # noqa: BLE001
        return ""
    if server.utcoffset() == local.utcoffset():
        return ""
    return (f"فرق {int((local.utcoffset() - server.utcoffset()).total_seconds() // 60)} "
            f"دقيقة عن {TZ} — لجدولة دقيقة بتوقيت الرياض استخدم mode=tick")


def install_cron(write=False, mode="tick", repo=None, python=None):
    """يطبع سطور cron، ومع --write يركّبها في crontab المستخدم (إزالة الوسم أولًا)."""
    block = crontab_lines(repo, python, mode)
    if not write:
        print(block)
        print("\n# للتركيب التلقائي: python3 engine/timing.py install-cron --write")
        return block
    try:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = current.stdout if current.returncode == 0 else ""
    except FileNotFoundError:
        print("❌ أمر `crontab` غير متوفر على هذا النظام — استخدم systemd timer "
              "(autostart/cron/*.timer) أو الوضع المقيم: python3 engine/timing.py loop")
        return block
    kept = [ln for ln in existing.splitlines() if CRON_MARK not in ln and ln.strip()]
    new = "\n".join(kept + [block]) + "\n"
    res = subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"❌ رفض crontab السطور: {res.stderr.strip()[:300]}")
        raise SystemExit(1)
    print(f"✅ رُكِّبت جدولة cron ({mode}). للتحقق: crontab -l | grep {CRON_MARK}")
    return block


def uninstall_cron(write=False, repo=None, python=None):
    block = crontab_lines(repo, python)
    if not write:
        print("# سطور ستُزال:")
        print(block)
        return block
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = current.stdout if current.returncode == 0 else ""
    kept = [ln for ln in existing.splitlines() if CRON_MARK not in ln]
    subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n",
                   capture_output=True, text=True)
    print("✅ أُزيلت سطور التوقيت من crontab.")
    return block


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="التوقيت التلقائي — بريف 06:30 ومسح كل 3 ساعات")
    ap.add_argument("cmd", nargs="?", default="status",
                    choices=["status", "list", "tick", "run", "loop", "next", "verify",
                             "install-cron", "uninstall-cron"])
    ap.add_argument("job", nargs="?", help="اسم الوظيفة لـ run: brief|sweep|review")
    ap.add_argument("--force", action="store_true", help="نفّذ ولو غير مستحقة")
    ap.add_argument("--write", action="store_true", help="طبّق على crontab فعليًا")
    ap.add_argument("--mode", choices=["tick", "native"], default="tick")
    ap.add_argument("--at", help="مرجع زمني للاختبار: YYYY-MM-DDTHH:MM")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="مخرج آلي (verify)")
    args = ap.parse_args(argv)

    ref = None
    if args.at:
        try:
            ref = dt.datetime.fromisoformat(args.at).replace(tzinfo=TZ)
        except ValueError:
            raise SystemExit(f"❌ صيغة وقت غير مفهومة: {args.at}")

    if args.cmd == "list":
        print(f"\n🕰️ التوقيت التلقائي — {TZ}\n" + "=" * 56)
        for j in timing_status()["jobs"]:
            print(f"  {j['emoji']} {j['job_id']:<22} {j['when']:<20} "
                  f"{'🟢' if j['due_now'] else '⚪'} {j['reason']}")
            print(f"      ↳ {j['name']} · القادم: {j['next']}")
        print()
        return
    if args.cmd == "status":
        print(json.dumps(timing_status(ref=ref), ensure_ascii=False, indent=2, default=str))
        return
    if args.cmd == "verify":
        report = verify(ref=ref)
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            print(verify_text(ref=ref))
        if report["verdict"] == "fail" and not args.as_json:
            raise SystemExit(1)     # الـ JSON يُترك للآلة تقرأ الحكم من الحقل
        return
    if args.cmd == "next":
        st = timing_status(ref=ref)
        for j in st["jobs"]:
            print(f"{j['emoji']} {j['job_id']} → {j['next']} · {j['reason']}")
        return
    if args.cmd == "tick":
        out = tick(ref=ref, verbose=True, trigger="cli")
        if out["status"] not in ("ok", "ran", "idle", "busy", "disabled"):
            raise SystemExit(1)
        return
    if args.cmd == "run":
        if not args.job:
            raise SystemExit("صيغة: python3 engine/timing.py run brief|sweep|review")
        res = run_job(args.job, force=True, ref=ref)
        if res["status"] == "error":
            raise SystemExit(1)
        return
    if args.cmd == "loop":
        loop()
        return
    if args.cmd == "install-cron":
        install_cron(write=args.write, mode=args.mode)
        return
    if args.cmd == "uninstall-cron":
        uninstall_cron(write=args.write)
        return
    print(__doc__)


if __name__ == "__main__":
    main()

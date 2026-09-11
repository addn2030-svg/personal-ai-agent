# -*- coding: utf-8 -*-
"""محرك الاستباقية (Proactive Chief of Staff) — v1.0.

الوضع الافتراضي: الانتظار ليس خيارًا. كل دورة تمر بالحلقة:

    رصد (Observe) ← تذكّر (Remember) ← توقّع (Predict) ← تسجيل نقاط (Score)
    ← قرار (Decide) ← تنفيذ/تجهيز/تنبيه (Act/Prepare/Alert) ← تعلّم (Learn)

المبدأ الحاكم: **نفّذ أولًا ما هو قابل للعكس ومنخفض الخطورة؛ اسأل أولًا في ما هو
غير قابل للعكس أو عالي الخطورة.** وقاعدة الحوكمة الأعلى (مطابقة v4.1.1) لا تُمس:
المحرك لا يرسل أي أثر خارجي أبدًا — كل ما يمس الخارج يخرج كمسودة في طابور
الاعتماد (action_queue → PENDING_APPROVAL) مهما بلغ مستوى الاستقلالية.

سلم الاستقلالية لكل فئة (لا يوجد مفتاح «تصرّف بحرية» عام):

  L0  اقتراح فقط          «يُستحسن أن ترد على X»
  L1  تجهيز/مسودة          مسودة رسالة، جدولة مقترحة، خطة
  L2  تنفيذ قابل للعكس     إنشاء مهمة، ملاحظة تحضير، حجز وقت داخلي — + تقرير
  L3  تنفيذ + تقرير        روتينيات داخلية مصرّح بها مسبقًا عبر أمر دائم
  L4  استقلالية كاملة      محجوز لروتينيات آمنة مصرّح بها صراحة (لا إرسال خارجيًا أبدًا)

الافتراضي: اتصالات خارجية/مالية/قانوني/صحي/سمعة ← L0/L1. جدولة داخلية/تذكيرات/
إنشاء مهام/تحضير ← L2/L3. أي ثقة دون 0.8 ← تجهيز بدل التنفيذ.

التشغيل:
  python3 engine/proactive.py sweep                     ← دورة رصد كاملة
  python3 engine/proactive.py brief                     ← البريف الاستباقي اليومي
  python3 engine/proactive.py status                    ← الحالة والعدادات
  python3 engine/proactive.py orders                    ← الأوامر الدائمة
  python3 engine/proactive.py order-disable SO-003      ← إيقاف أمر دائم
  python3 engine/proactive.py pause --hours 4 | resume  ← مفتاح الإيقاف المؤقت
  python3 engine/proactive.py undo PA-0001              ← زر التراجع عن تنفيذ
  python3 engine/proactive.py feedback PA-0001 good     ← تعلّم: good|much|never
  python3 engine/proactive.py push-test                 ← تجربة قناة تنبيه تيليجرام

قناة التنبيه المستعجل (تيليجرام): تفعَّل تلقائيًا عند توفر TELEGRAM_BOT_TOKEN
ومعرّف المحادثة (TELEGRAM_ALLOWED_CHAT_ID أو ملف المالك الذي يصنعه البوت عند أول
محادثة خاصة). تدفع حوادث proactive_alert فقط — أي ما اجتاز سقف اليوم وساعات
الهدوء أصلًا — ولا تدخل في ذرّية الحالة، وفشلها موثَّق ولا يُسقط الدورة.
للإيقاف الكامل: PROACTIVE_TELEGRAM_PUSH=0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as _store_mod
from store import Store, log_event

TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

# ---------------------------------------------------------------- الإعدادات والحواجز
DEFAULT_CFG = {
    # عتبة الثقة: دونها «تجهيز» دائمًا بدل «تنفيذ»
    "confidence_act": float(os.environ.get("PROACTIVE_CONFIDENCE_THRESHOLD", "0.8")),
    # سقف التنبيهات الفورية يوميًا — الفائض يُدفع للبريف (لا إغراق)
    "max_alerts": int(os.environ.get("PROACTIVE_MAX_ALERTS", "6")),
    # ساعات الهدوء: لا تنبيهات داخلها إلا الأحمر الذي تنتهي مهلته خلال ساعتين
    "quiet_start": os.environ.get("PROACTIVE_QUIET_START", "22:00"),
    "quiet_end": os.environ.get("PROACTIVE_QUIET_END", "06:30"),
    "meeting_window_min": int(os.environ.get("PROACTIVE_MEETING_WINDOW_MIN", "30")),
    "deadline_window_h": int(os.environ.get("PROACTIVE_DEADLINE_WINDOW_H", "48")),
    "aging_days": int(os.environ.get("PROACTIVE_AGING_DAYS", "3")),
    "renew_red_days": int(os.environ.get("PROACTIVE_RENEW_RED_DAYS", "3")),
    "renew_watch_days": int(os.environ.get("PROACTIVE_RENEW_WATCH_DAYS", "7")),
    "unused_days": int(os.environ.get("PROACTIVE_UNUSED_DAYS", "45")),
    "conflict_days": int(os.environ.get("PROACTIVE_CONFLICT_DAYS", "3")),
    "travel_window_h": int(os.environ.get("PROACTIVE_TRAVEL_WINDOW_H", "24")),
    "slip_days": int(os.environ.get("PROACTIVE_SLIP_DAYS", "7")),
    "focus_gap_min": int(os.environ.get("PROACTIVE_FOCUS_GAP_MIN", "90")),
    "focus_day_start": os.environ.get("PROACTIVE_FOCUS_DAY_START", "09:00"),
    "focus_day_end": os.environ.get("PROACTIVE_FOCUS_DAY_END", "17:00"),
    "demote_days": int(os.environ.get("PROACTIVE_DEMOTE_DAYS", "14")),
}

LEVELS = ["L0", "L1", "L2", "L3", "L4"]
LEVEL_AR = {
    "L0": "اقتراح فقط", "L1": "تجهيز مسودة", "L2": "تنفيذ قابل للعكس + تقرير",
    "L3": "تنفيذ + تقرير", "L4": "استقلالية كاملة (مقيدة داخليًا)",
}

# مصفوفة الاستقلالية لكل فئة — لا مفتاح عام. الفئات الحساسة أبدًا فوق L1.
AUTONOMY_MATRIX = {
    "external_comms": "L1",   # مسودة + طلب اعتماد بنقرة
    "money":          "L1",   # تجهيز/تنبيه فقط — لا أموال تتحرك آليًا
    "legal":          "L0",
    "health":         "L0",
    "reputation":     "L1",
    "internal_sched": "L3",
    "reminders":      "L3",
    "task_creation":  "L2",
    "prep_work":      "L2",
}
RED_CATEGORIES = {"money", "legal", "health"}   # أحمر: تنبيه فوري وتوصية — لا تنفيذ
RISK_FACTOR = {"low": 1.0, "medium": 0.85, "high": 0.6}
PRIO_IMPACT = {"عالية": 5, "متوسطة": 3, "منخفضة": 1}
DONE_WORDS = ("منجز", "تم", "CLOSED", "DONE")

# الأوامر الدائمة المصرّح بها مسبقًا — تُزرع في الحالة عند أول دورة ويمكن
# تعديلها/إيقافها من هناك دون تغيير الكود.
DEFAULT_STANDING_ORDERS = [
    {"order_id": "SO-001", "kind": "meeting_prep", "enabled": True,
     "name": "اجتماع خلال 30 دقيقة ← ملاحظة تحضير وجدول أعمال",
     "category": "prep_work", "level": "L2", "pre_approved": True, "params": {}},
    {"order_id": "SO-002", "kind": "deadline_48h", "enabled": True,
     "name": "موعد نهائي خلال 48 ساعة دون نافذة عمل ← حجز نافذة تركيز",
     "category": "internal_sched", "level": "L2", "pre_approved": True, "params": {}},
    {"order_id": "SO-003", "kind": "aging_followup", "enabled": True,
     "name": "انتظار بلا رد يتجاوز N أيام (قبل التعفّن) ← مسودة متابعة للاعتماد",
     "category": "external_comms", "level": "L1", "pre_approved": False, "params": {}},
    {"order_id": "SO-004", "kind": "bill_due", "enabled": True,
     "name": "التزام مالي خلال 3 أيام ← تنبيه أحمر + تعليمة دفع في طابور الاعتماد",
     "category": "money", "level": "L1", "pre_approved": True, "params": {}},
    {"order_id": "SO-005", "kind": "renewal_watch", "enabled": True,
     "name": "تجديد خلال 7 أيام ← تلخيص الشروط وتجهيز قرار التجديد",
     "category": "money", "level": "L1", "pre_approved": True, "params": {}},
    {"order_id": "SO-006", "kind": "calendar_conflict", "enabled": True,
     "name": "تعارض مواعيد ← تنبيه ومسودة إعادة جدولة للموعد الأدنى أثرًا",
     "category": "reputation", "level": "L1", "pre_approved": True, "params": {}},
    {"order_id": "SO-007", "kind": "travel_24h", "enabled": True,
     "name": "سفر خلال 24 ساعة ← قائمة وثائق ومسار رحلة ومسودة check-in",
     "category": "prep_work", "level": "L1", "pre_approved": False, "params": {}},
    {"order_id": "SO-008", "kind": "missed_recovery", "enabled": True,
     "name": "التزام فائت ← خطة استدراك (تنفيذ داخلي أو مسودة للاعتماد) — لا سقوط صامت",
     "category": "reminders", "level": "L2", "pre_approved": True, "params": {}},
]

now = lambda: dt.datetime.now(TZ)


# ---------------------------------------------------------------- قناة التنبيه المستعجل (تيليجرام)
# يدفع حوادث proactive_alert — وحدها ما اجتاز الحواجز (السقف اليومي/الهدوء) أصلًا.
# نفس اصطلاحات connectors/telegram_bot_legacy: التوكن في البيئة فقط، ومعرف المحادثة
# من TELEGRAM_ALLOWED_CHAT_ID ثم ملف المالك (أول محادثة خاصة مع البوت).
TELEGRAM_API = "https://api.telegram.org"


def _push_disabled():
    return os.environ.get("PROACTIVE_TELEGRAM_PUSH", "1") == "0"


def _telegram_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _telegram_chat_id():
    env = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if env:
        return env
    for folder in (_store_mod.DATA_DIR, os.path.join(BASE, "data")):
        try:
            with open(os.path.join(folder, ".telegram-owner-chat-id"),
                      encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            continue
    return ""


def _telegram_send(text, chat_id=None, token=None, timeout=15):
    """دالة الشبكة الخام — قابلة للاستبدال في الاختبارات. ترجع True عند ok."""
    token = token or _telegram_token()
    chat_id = chat_id or _telegram_chat_id()
    if not token or not chat_id:
        return False
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500]}).encode()
    req = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/sendMessage", data=payload)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {data}")
    return True


def telegram_push_status():
    if _push_disabled():
        return "disabled_env"
    if not _telegram_token():
        return "no_token"
    if not _telegram_chat_id():
        return "no_chat_id"
    return "ready"


def _alert_text(t, row):
    red = row.get("lane") == "RED"
    icon = "⛔" if red else "⚠️"
    head = "تنبيه استباقي أحمر" if red else "تنبيه استباقي"
    lines = [f"{icon} {head} — {t.date().isoformat()}", str(row.get("title", ""))]
    if row.get("note"):
        lines.append(str(row["note"]))
    if row.get("quiet_override"):
        lines.append("🌙 تجاوز ساعات الهدوء موثَّقًا لاستعجال المهلة (<ساعتين).")
    lines += [f"🗂 التفاصيل والاعتمادات: reports/proactive-brief-{t.date().isoformat()}.md",
              f"↩️ تراجع: undo {row.get('pa_id')} · 🚫 إيقاف النوع: "
              f"feedback {row.get('pa_id')} never · ⏸️ إيقاف: pause --hours 4"]
    return "\n".join(l for l in lines if l)


def _push_alerts(t, events, alert_rows, verbose):
    """يدفع تنبيهات الدورة للمحادثة المالكة — فشل الشبكة لا يُسقط الدورة أبدًا."""
    pushed = 0
    if not alert_rows or _push_disabled():
        return pushed
    status = telegram_push_status()
    if status != "ready":
        if verbose:
            print(f"📵 قناة تيليجرام للتنبيهات: {status} — التنبيهات في البريف فقط.")
        return pushed
    chat_id, token = _telegram_chat_id(), _telegram_token()
    for row in alert_rows:
        try:
            if _telegram_send(_alert_text(t, row), chat_id=chat_id, token=token):
                pushed += 1
                log_event("proactive_alert_pushed", pa_id=row.get("pa_id"),
                          lane=row.get("lane"))
        except Exception as exc:  # noqa: BLE001 — القناة اختيارية؛ موثَّقة ولا تُسقط
            log_event("proactive_push_error", pa_id=row.get("pa_id"),
                      error=str(exc)[:160])
    return pushed
def _hash(txt):
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def _as_date(x):
    if x in (None, "", "NEEDS_INPUT"):
        return None
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _as_dt(x):
    """يحلل طوابع زمنية تخزن كسلاسل أو datetimes (parse_dates تعيد تحويلها)."""
    if x in (None, ""):
        return None
    if isinstance(x, dt.datetime):
        out = x
    else:
        try:
            out = dt.datetime.fromisoformat(str(x).replace(" ", "T"))
        except (TypeError, ValueError):
            return None
    return out if out.tzinfo else out.replace(tzinfo=TZ)


def _meeting_dt(m):
    d = _as_date(m.get("التاريخ"))
    if not d:
        return None
    try:
        hh, mm = (str(m.get("الوقت") or "00:00").split(":") + ["0"])[:2]
        return dt.datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=TZ)
    except (TypeError, ValueError):
        return dt.datetime(d.year, d.month, d.day, tzinfo=TZ)


def _hm(txt):
    hh, mm = txt.split(":")
    return dt.time(int(hh), int(mm))


def _in_quiet(t, cfg):
    start, end = _hm(cfg["quiet_start"]), _hm(cfg["quiet_end"])
    cur = t.time().replace(second=0, microsecond=0)
    return (cur >= start or cur < end) if start > end else (start <= cur < end)


def _urg_from_days(days):
    if days is None:
        return 1
    if days <= 0:
        return 5
    if days <= 1:
        return 4
    if days <= 2:
        return 3
    if days <= 7:
        return 2
    return 1


def _task_done(t):
    return any(str(t.get("الحالة", "")).startswith(w) for w in DONE_WORDS)


def _is_proactive_task(t):
    return str(t.get("المصدر", "")).startswith("proactive:")


def _order(S, kind):
    for o in S.get("standing_orders", []):
        if o.get("kind") == kind:
            return o
    return None


def _enabled(S, kind):
    o = _order(S, kind)
    return bool(o and o.get("enabled"))


def _marker(t):
    return t.isoformat(timespec="minutes")


# ---------------------------------------------------------------- رصد ← تذكّر: سجل الحلقات المفتوحة
def refresh_open_loops(S, t):
    """Open Loops Ledger: التزاماتي لنفسي، التزامات الآخرين لي، مواعيد وتجديدات،
    قرارات ومخاطر. upsert بمعرف حتمي (النوع+العنوان) وإغلاق ما تحقق مصدره —
    ولا كتابة إن لم يتغير شيء مادي (write-on-change)."""
    loops = {l["loop_id"]: l for l in S.setdefault("open_loops", [])}
    changed = False

    def upsert(kind, title, due, impact, source, owner="عبدالرحمن", closed=False,
               confidence=1.0):
        nonlocal changed
        lid = "OL-" + _hash(kind + "|" + str(title))[:8]
        existing = loops.get(lid)
        due_s = _as_date(due)  # صيغة موحدة (date|None) تصمد أمام ذهاب-وإياب parse_dates
        material = {"kind": kind, "title": title, "owner": owner, "due": due_s,
                    "impact": impact, "confidence": confidence, "source": source}
        if existing is None:
            loops[lid] = {**material, "loop_id": lid,
                          "status": "CLOSED" if closed else "OPEN",
                          "created_at": _marker(t), "updated_at": _marker(t),
                          "closed_at": _marker(t) if closed else None}
            changed = True
            return loops[lid]
        current = {k: existing.get(k) for k in material}
        current["due"] = _as_date(current.get("due"))
        new_status = existing.get("status")
        closed_at = existing.get("closed_at")
        if closed and new_status != "CLOSED":
            new_status, closed_at = "CLOSED", _marker(t)
        elif closed is False and current != material:
            # تغيّر مادي على عنصر ما زال مفتوحًا (تقدّم الموعد مثلًا) ← أعد فتحه
            if str(new_status) == "CLOSED":
                new_status, closed_at = "OPEN", None
        if current != material or new_status != existing.get("status") \
                or str(closed_at) != str(existing.get("closed_at")):
            existing.update(material)
            existing["status"] = new_status
            existing["closed_at"] = closed_at
            existing["updated_at"] = _marker(t)
            changed = True
        return existing

    for task in S.get("tasks", []):
        if _is_proactive_task(task):
            continue  # مهام المحرك نفسه ليست حلقاتًا ضده
        due = _as_date(task.get("الموعد النهائي"))
        upsert("i_promised", task.get("العنوان", "مهمة"), due,
               PRIO_IMPACT.get(task.get("الأولوية"), 3),
               {"section": "tasks", "type": task.get("النوع")},
               closed=_task_done(task), confidence=1.0 if due else 0.6)

    for w in S.get("waiting_for", []):
        due = _as_date(w.get("expected_by"))
        upsert("they_promised", w.get("task") or w.get("item") or "عنصر انتظار", due, 4,
               {"section": "waiting_for", "from": w.get("expected_from")},
               owner=w.get("expected_from") or "—",
               closed=w.get("status") not in ("WAITING", "OVERDUE"),
               confidence=1.0 if due else 0.6)

    pending_drs = set()
    for dr in S.get("decision_requests", []):
        if dr.get("status") == "PENDING":
            pending_drs.add(dr.get("id"))
            upsert("decision", dr.get("title") or dr.get("id"),
                   _as_date(dr.get("deadline")), 4,
                   {"section": "decision_requests", "id": dr.get("id")})
    for l in loops.values():  # قرار حُسم خارج الدورة ← أغلق حلقته
        if l.get("kind") == "decision" and l.get("status") != "CLOSED":
            src_id = (l.get("source") or {}).get("id")
            if src_id and src_id not in pending_drs:
                l["status"], l["closed_at"], l["updated_at"] = "CLOSED", _marker(t), _marker(t)
                changed = True

    for f in S.get("finance", []):
        due = _as_date(f.get("تاريخ التجديد"))
        if due:
            upsert("renewal", "تجديد: " + str(f.get("البند")), due, 4,
                   {"section": "finance", "cost": f.get("التكلفة (ريال/شهر)")})

    for p in S.get("projects", []):
        last = _as_date(p.get("آخر تقدم"))
        stalled = (p.get("الحالة") == "نشط" and last
                   and last < t.date() - dt.timedelta(days=30))
        upsert("risk", "مشروع بلا تقدم: " + str(p.get("المشروع")),
               last + dt.timedelta(days=30) if last else None, 3,
               {"section": "projects", "status": p.get("الحالة")}, closed=not stalled)

    S["open_loops"] = sorted(loops.values(), key=lambda l: (str(l.get("due") or "9999")))
    return changed


# ---------------------------------------------------------------- توقّع: مولدات المحفزات (نقية — بلا كتابة)
def _cand(key, kind, title, body, category, impact, urgency, confidence, risk,
          reversibility, hint, due=None, loop_id=None, override_quiet=False,
          channel="wa/email", action_type=None):
    return {"key": key, "kind": kind, "title": title, "body": body,
            "category": category, "impact": impact, "urgency": urgency,
            "confidence": confidence, "risk": risk, "reversibility": reversibility,
            "hint": hint, "due": due.isoformat() if isinstance(due, dt.date) else due,
            "loop_id": loop_id, "override_quiet": override_quiet,
            "channel": channel, "action_type": action_type or kind}


def collect_candidates(S, t, cfg):
    """يفحص المحفزات الستة: زمني، حدثي، حالوي، نمطي، شاذ، فرصي. دالة نقية: لا تكتب."""
    cands = []
    today = t.date()

    # --- زمني: اجتماع وشيك (أمر دائم SO-001؛ الفجوة اقتراح فقط) ---
    if _enabled(S, "meeting_prep"):
        for m in S.get("meetings", []):
            mdt = _meeting_dt(m)
            if not mdt or mdt.date() != today:
                continue
            mins = (mdt - t).total_seconds() / 60
            prep_missing = not str(m.get("حالة التحضير", "")).startswith("جاهز")
            ref = str(m.get("الموضوع")) + "|" + str(m.get("الوقت"))
            if 0 <= mins <= cfg["meeting_window_min"]:
                body = (f"ملاحظة تحضير لاجتماع «{m.get('الموضوع')}» ({m.get('الوقت')}):\n"
                        f"الهدف: {m.get('الهدف') or '—'}\nالحضور: {m.get('الحضور') or '—'}\n"
                        f"التحضير المطلوب: {m.get('التحضير المطلوب') or '—'}\n"
                        "جدول أعمال مقترح: 1) الافتتاح والنتيجة المطلوبة 2) البنود "
                        "3) قرارات وخطوات تالية.")
                cands.append(_cand(f"meeting_prep|{ref}|{today}", "meeting_prep",
                                   f"تحضير اجتماع: {m.get('الموضوع')}", body,
                                   "prep_work", 3, 5 if prep_missing else 3, 0.95,
                                   "low", "reversible", "create_task",
                                   due=today, override_quiet=True))
            elif mins > cfg["meeting_window_min"] and prep_missing:
                cands.append(_cand(f"meeting_prep_gap|{ref}|{today}", "meeting_prep_gap",
                                   f"ينقص تحضير: {m.get('الموضوع')}",
                                   f"اجتماع «{m.get('الموضوع')}» اليوم {m.get('الوقت')} "
                                   f"وحالته «{m.get('حالة التحضير')}». المطلوب: "
                                   f"{m.get('التحضير المطلوب') or '—'}.",
                                   "prep_work", 3, 3, 0.9, "low", "reversible",
                                   "suggest", due=today))

    # --- زمني: موعد نهائي خلال 48 ساعة دون نافذة عمل (SO-002) ---
    if _enabled(S, "deadline_48h"):
        horizon = (t + dt.timedelta(hours=cfg["deadline_window_h"])).date()
        focus_titles = [x.get("العنوان", "") for x in S.get("tasks", [])
                        if _is_proactive_task(x) and not _task_done(x)]
        for task in S.get("tasks", []):
            if _task_done(task) or _is_proactive_task(task):
                continue
            due = _as_date(task.get("الموعد النهائي"))
            if not due or due < today or due > horizon:
                continue
            if any(task["العنوان"] in x for x in focus_titles):
                continue
            body = (f"الموعد النهائي لـ«{task['العنوان']}» {due.isoformat()} "
                    f"(أولوية {task.get('الأولوية')}) ولا نافذة عمل محجوزة. "
                    "حُجزت نافذة تركيز اليوم لإنجاز مسودة أولى.")
            cands.append(_cand(f"deadline_48h|{task['العنوان']}|{today}", "deadline_48h",
                               f"نافذة تركيز: {task['العنوان']}", body,
                               "internal_sched",
                               PRIO_IMPACT.get(task.get("الأولوية"), 3),
                               _urg_from_days((due - today).days), 0.9, "low",
                               "reversible", "create_task", due=due))

    # --- حدثي/نمطي: انتظار بلا رد N أيام ولم يتعفّن بعد (SO-003) ---
    if _enabled(S, "aging_followup"):
        for w in S.get("waiting_for", []):
            if w.get("status") != "WAITING":
                continue  # المتأخر يعالجه المدير ومسار الاستدراك
            since = _as_date(w.get("since")) or _as_date(w.get("expected_by"))
            if not since or (today - since).days < cfg["aging_days"]:
                continue
            due = _as_date(w.get("expected_by"))
            if due and due < today:
                continue
            who = w.get("expected_from") or "الطرف الآخر"
            draft = w.get("follow_up_draft") or (
                f"السلام عليكم، أتابع بخصوص «{w.get('task')}» — هل من تحديث؟ (عبدالرحمن)")
            body = (f"بلا رد منذ {(today - since).days} أيام: «{w.get('task')}» "
                    f"(منتظر من {who}).\nالمسودة المقترحة:\n{draft}")
            cands.append(_cand(f"aging_followup|{w.get('wid') or w.get('task')}|{today}",
                               "aging_followup", f"متابعة قبل التعفّن: {w.get('task')}",
                               body, "external_comms", 4, 3, 0.9, "medium", "reversible",
                               "enqueue", due=due))

    # --- مالي: استحقاق ≤3 أيام أحمر (SO-004) / تجديد ≤7 أيام تجهيز قرار (SO-005) ---
    for f in S.get("finance", []):
        due = _as_date(f.get("تاريخ التجديد"))
        cost = f.get("التكلفة (ريال/شهر)") or 0
        last_use = _as_date(f.get("آخر استخدام"))
        if due:
            days = (due - today).days
            if 0 <= days <= cfg["renew_red_days"] and _enabled(S, "bill_due"):
                body = (f"تنبيه أحمر: التزام مالي «{f.get('البند')}» يستحق خلال {days} "
                        f"يوم ({due.isoformat()}) — {cost} ريال/شهر.\n"
                        "التوصية: مراجعة الكشف وتجهيز السداد قبل الاستحقاق. جهّزت "
                        "تعليمة دفع في طابور الاعتماد — التنفيذ بيدك وحدك بنقرة.")
                cands.append(_cand(f"bill_due|{f.get('البند')}|{due}", "bill_due",
                                   f"استحقاق مالي وشيك: {f.get('البند')}", body,
                                   "money", 5, 5, 0.95, "high", "irreversible",
                                   "enqueue", due=due, override_quiet=days <= 1,
                                   action_type="payment_instruction"))
            elif cfg["renew_red_days"] < days <= cfg["renew_watch_days"] and _enabled(S, "renewal_watch"):
                unused_note = ("\n⚠️ البند غير مستخدم منذ فترة — الإلغاء مرشّح بقوة."
                               if last_use and (today - last_use).days > 30 else "")
                body = (f"تجديد خلال {days} أيام: «{f.get('البند')}» ({due.isoformat()}, "
                        f"{cost} ريال/شهر).{unused_note}\n"
                        "ملخص القرار: تجديد / إلغاء / تفاوض. جهّزت مذكرة القرار للاعتماد.")
                # نافذة 7 أيام = تجهيز قرار مبكر (أصفر)؛ الأحمر يبدأ عند ≤3 أيام
                cands.append(_cand(f"renewal_watch|{f.get('البند')}|{due}",
                                   "renewal_watch", f"قرار تجديد: {f.get('البند')}", body,
                                   "money", 4, 2, 0.9, "medium", "reversible",
                                   "enqueue", due=due, action_type="renewal_decision"))
        # فرصة مالية: اشتراك غير مستخدم (اقتراح فقط)
        if last_use and (today - last_use).days > cfg["unused_days"] and cost > 0:
            cands.append(_cand(f"unused_subscription|{f.get('البند')}|{today}",
                               "unused_subscription",
                               f"اشتراك غير مستخدم: {f.get('البند')}",
                               f"«{f.get('البند')}» بلا استخدام منذ {(today - last_use).days} "
                               f"يومًا ويكلف {cost} ريال/شهر — إلغاؤه يوفر {cost * 12} "
                               "ريال/سنة.", "money", 2, 1, 0.85, "medium", "reversible",
                               "suggest"))

    # --- شاذ: تعارض مواعيد (SO-006؛ افتراض 60 دقيقة للاجتماع) ---
    if _enabled(S, "calendar_conflict"):
        by_day = {}
        for m in S.get("meetings", []):
            mdt = _meeting_dt(m)
            if mdt and today <= mdt.date() <= today + dt.timedelta(days=cfg["conflict_days"]):
                by_day.setdefault(mdt.date(), []).append((mdt, m))
        for day, items in sorted(by_day.items()):
            items.sort(key=lambda x: x[0])
            for (a_dt, a), (b_dt, b) in zip(items, items[1:]):
                if b_dt < a_dt + dt.timedelta(hours=1):
                    body = (f"تعارض مواعيد {day.isoformat()}: «{a.get('الموضوع')}» "
                            f"({a.get('الوقت')}) مع «{b.get('الموضوع')}» ({b.get('الوقت')}).\n"
                            "الحل المقترح: الاحتفاظ بالأعلى أثرًا، ومسودة اعتذار/إعادة "
                            "جدولة للآخر جاهزة للاعتماد.")
                    cands.append(_cand(f"calendar_conflict|{day}|{a.get('الموضوع')}",
                                       "calendar_conflict", f"تعارض مواعيد {day.isoformat()}",
                                       body, "reputation", 4,
                                       _urg_from_days((day - today).days), 0.85, "medium",
                                       "reversible", "enqueue", due=day,
                                       override_quiet=(day == today)))

    # --- زمني: سفر خلال 24 ساعة (SO-007) ---
    if _enabled(S, "travel_24h"):
        horizon = t + dt.timedelta(hours=cfg["travel_window_h"])
        for coll, topic_key in (("meetings", "الموضوع"), ("tasks", "العنوان")):
            for x in S.get(coll, []):
                title = str(x.get(topic_key) or "")
                if not any(w in title for w in ("سفر", "رحلة", "تأشيرة")):
                    continue
                xd = _meeting_dt(x) if coll == "meetings" else None
                if xd is None:
                    d = _as_date(x.get("الموعد النهائي") or x.get("التاريخ"))
                    if not d:
                        continue
                    xd = dt.datetime.combine(d, dt.time(9), TZ)
                if not (t <= xd <= horizon):
                    continue
                body = (f"سفر خلال {int((xd - t).total_seconds() // 3600)} ساعة: «{title}».\n"
                        "جهّزت قائمة الوثائق (هوية/حجوزات/تأشيرة) ومسار الرحلة ومسودة "
                        "تذكير check-in — في طابور الاعتماد.")
                cands.append(_cand(f"travel_24h|{title}|{today}", "travel_24h",
                                   f"تجهيز سفر: {title}", body,
                                   "prep_work", 4, 5, 0.85, "medium", "reversible",
                                   "enqueue", due=xd.date(), override_quiet=True))

    # --- فرصي: أول فجوة تركيز حرة اليوم (اقتراح فقط — بلا حجز تلقائي) ---
    today_meetings = sorted(mt for mt in
                            (_meeting_dt(x) for x in S.get("meetings", []))
                            if mt and mt.date() == today)
    cursor = max(dt.datetime.combine(today, _hm(cfg["focus_day_start"]), TZ), t)
    day_end = dt.datetime.combine(today, _hm(cfg["focus_day_end"]), TZ)
    gap = None
    for mdt in today_meetings:
        if mdt <= cursor:
            cursor = max(cursor, mdt + dt.timedelta(hours=1))
            continue
        if (mdt - cursor).total_seconds() / 60 >= cfg["focus_gap_min"]:
            gap = (cursor, mdt)
            break
        cursor = max(cursor, mdt + dt.timedelta(hours=1))
    if gap is None and (day_end - cursor).total_seconds() / 60 >= cfg["focus_gap_min"]:
        gap = (cursor, day_end)
    if gap:
        cands.append(_cand(f"free_slot|{today}", "free_slot",
                           f"فجوة تركيز {gap[0]:%H:%M}–{gap[1]:%H:%M}",
                           f"أول فجوة حرة اليوم {gap[0]:%H:%M}–{gap[1]:%H:%M} — نافذة "
                           "مثالية لأعلى مهمة أولوية.", "internal_sched", 2, 2, 0.8,
                           "low", "reversible", "suggest", due=today))

    # --- نمطي: مهمة تنزلق منذ أسبوع+ ← قرار ثلاثي ---
    for task in S.get("tasks", []):
        if _task_done(task) or _is_proactive_task(task):
            continue
        due = _as_date(task.get("الموعد النهائي"))
        if due and (today - due).days >= cfg["slip_days"]:
            cands.append(_cand(f"slipping_task|{task['العنوان']}|{today}", "slipping_task",
                               f"مهمة تنزلق: {task['العنوان']}",
                               f"«{task['العنوان']}» متأخرة {(today - due).days} يومًا — "
                               "نمط تأجيل متكرر؟ قرر: جدولة نافذة اليوم / تفويض / "
                               "حذف بلا شعور بالذنب.", "reminders",
                               PRIO_IMPACT.get(task.get("الأولوية"), 3), 2, 0.85, "low",
                               "reversible", "suggest", due=due))

    # --- حدثي: طلب قرار تقترب مهلته (خلال 24 ساعة) ---
    for dr in S.get("decision_requests", []):
        if dr.get("status") != "PENDING":
            continue
        dl = _as_date(dr.get("deadline"))
        if dl and dl <= today + dt.timedelta(days=1):
            cands.append(_cand(f"decision_watch|{dr.get('id')}|{today}", "decision_watch",
                               f"قرار ينتظرك: {dr.get('title')}",
                               f"مهلة «{dr.get('title')}» ({dr.get('id')}) تنتهي "
                               f"{dl.isoformat()}.\nالخيارات: "
                               + " / ".join(dr.get("options", [])),
                               "reminders", 4, 4, 0.95, "low", "reversible", "alert",
                               due=dl))
    return cands


# ---------------------------------------------------------------- تسجيل النقاط والقرار
def score(cand):
    """impact × urgency × confidence، مُرجّحة بعامل الخطورة والعكوسية."""
    s = cand["impact"] * cand["urgency"] * cand["confidence"]
    s *= RISK_FACTOR.get(cand["risk"], 0.85)
    if cand["reversibility"] == "irreversible":
        s *= 0.7
    return round(s, 2)


def _feedback_rules(S):
    never_kinds, never_cats, demoted = set(), set(), {}
    for fb in S.get("proactive_feedback", []):
        if fb.get("signal") == "never":
            (never_cats if fb.get("scope") == "category" else never_kinds).add(fb.get("target"))
        elif fb.get("signal") == "much":
            until = _as_date(fb.get("until"))
            if until:
                demoted[fb.get("target")] = until
    return {"never_kinds": never_kinds, "never_categories": never_cats, "demoted": demoted}


def decide(cand, S, t, cfg, rules):
    """يعيد (decision, lane, note).

    القواعد: أحمر (مالي/قانوني/صحي، عالي الخطورة، غير قابل للعكس) ← تنبيه فوري
    ولا تنفيذ آلي أبدًا ولا يخفضه تفضيل «أبدًا». أخضر يتطلب: مستوى ≥L2 + قابل
    للعكس + خطورة منخفضة + مصرّح مسبقًا + ثقة ≥ العتبة — وإلا يُخفَّض لتجهيز.
    """
    order = _order(S, cand["kind"])
    level = (order or {}).get("level") or AUTONOMY_MATRIX.get(cand["category"], "L0")
    lvl = LEVELS.index(level)
    # أحمر: فئة حرجة باستعجال حقيقي، أو خطورة عالية، أو أثر غير قابل للعكس.
    # (الفئة الحرجة بلا استعجال تبقى تجهيزًا/اقتراحًا كي لا نغرقك بالتنبيهات)
    red = (cand["risk"] == "high" or cand["reversibility"] == "irreversible"
           or (cand["category"] in RED_CATEGORIES and cand["urgency"] >= 4))

    if cand["kind"] in rules["never_kinds"] or cand["category"] in rules["never_categories"]:
        if red:
            return "ALERT", "RED", "تفضيل «أبدًا» مسجّل، لكن التنبيه الأحمر يتجاوزه لحمايتك"
        return "SKIPPED_FEEDBACK", "INFO", "أوقفته تغذية راجعة سابقة («أبدًا»)"

    if red:
        draft = bool(order and (order.get("pre_approved") or lvl >= 1)
                     and cand["hint"] == "enqueue")
        return ("ALERT_DRAFT" if draft else "ALERT"), "RED", \
            "عالي الخطورة/غير قابل للعكس — تنبيه فوري وتوصية، لا تنفيذ آلي" + \
            (" + مسودة بانتظار اعتمادك" if draft else "")

    if rules["demoted"].get(cand["kind"], dt.date.min) >= t.date():
        return "SUGGEST", "INFO", "خُفّض للبريف فقط بناءً على تغذية «كثير»"

    if cand["hint"] == "alert":
        return "ALERT", "YELLOW", "تنبيه مبكر — لا إجراء خارجي مطلوب"

    if cand["hint"] == "create_task" and lvl >= 2 and cand["reversibility"] == "reversible" \
            and cand["risk"] == "low" and (not order or order.get("pre_approved")):
        if cand["confidence"] >= cfg["confidence_act"]:
            return "ACT", "GREEN", f"{level} قابل للعكس ومنخفض الخطورة ومصرّح — نُفّذ وسيُبلَّغ"
        return "PREPARE", "YELLOW", \
            f"ثقة {cand['confidence']:.2f} < {cfg['confidence_act']} — تجهيز بدل التنفيذ"

    if cand["hint"] == "enqueue" and lvl >= 1:
        return "PREPARE", "YELLOW", f"{level} تجهيز كامل — ينتظر اعتمادك بنقرة"

    return "SUGGEST", "INFO", f"{level} اقتراح فقط في البريف"


# ---------------------------------------------------------------- تنفيذ/تجهيز/تنبيه
def _apply_candidate(S, cand, t, cfg, events):
    pa_id = "PA-%04d" % (len(S.get("proactive_actions", [])) + 1)
    rules = _feedback_rules(S)
    decision, lane, note = decide(cand, S, t, cfg, rules)
    row = {"pa_id": pa_id, "ts": t.isoformat(timespec="seconds"), "key": cand["key"],
           "kind": cand["kind"], "title": cand["title"], "category": cand["category"],
           "impact": cand["impact"], "urgency": cand["urgency"],
           "confidence": cand["confidence"], "reversibility": cand["reversibility"],
           "risk": cand["risk"], "score": score(cand), "lane": lane,
           "decision": decision, "note": note,
           "standing_order": (_order(S, cand["kind"]) or {}).get("order_id"),
           "result": {}, "undo": None, "status": "INFO"}

    if decision == "ACT":
        task = {"العنوان": cand["title"], "النوع": "استباقي",
                "الأولوية": "عالية" if cand["impact"] >= 4 else "متوسطة",
                "الموعد النهائي": cand["due"] or t.date().isoformat(),
                "الحالة": "لم تبدأ", "السياق/المشروع": "استباقي",
                "المصدر": "proactive:" + pa_id,
                "ملاحظات": f"[{pa_id}] {cand['body'][:160]}"}
        S.setdefault("tasks", []).append(task)
        row["undo"] = {"op": "remove_task", "pa_id": pa_id}
        row["result"] = {"task_title": cand["title"]}
        row["status"] = "DONE"
        events.append(("proactive_act", {"pa_id": pa_id, "kind": cand["kind"],
                                         "title": cand["title"][:80]}))
    elif decision in ("PREPARE", "ALERT_DRAFT"):
        queue = S.setdefault("action_queue", [])
        h = _hash(cand["body"])
        if any(a.get("content_hash") == h for a in queue):
            row["result"] = {"already_queued": True}
        else:
            aq_id = "A-%03d" % (len(queue) + 1)
            queue.append({"action_id": aq_id, "type": cand["action_type"],
                          "channel": cand["channel"], "content": cand["body"],
                          "content_hash": h, "status": "PENDING_APPROVAL",
                          "created_at": t.date().isoformat(),
                          "expires_at": (t.date() + dt.timedelta(days=2)).isoformat(),
                          "approved_at": None, "executed_at": None,
                          "origin": "proactive", "proactive_id": pa_id})
            row["result"] = {"action_id": aq_id}
            events.append(("action_enqueued", {"action_id": aq_id, "hash": h,
                                               "origin": "proactive"}))
        row["status"] = "QUEUED"
        if decision == "ALERT_DRAFT":
            _alert(S, row, cand, t, cfg, events)
    elif decision == "ALERT":
        _alert(S, row, cand, t, cfg, events)
    S.setdefault("proactive_actions", []).append(row)
    return row


def _alert(S, row, cand, t, cfg, events):
    """حواجز التنبيه: سقف يومي + ساعات هدوء (تجاوز الأحمر فائق الاستعجال موثَّق).
    يُحصى ما سبق في الدفتر نفسه — لأن صفوف هذه الدورة أُلحقت بالفعل قبل النداء."""
    already = sum(1 for a in S.get("proactive_actions", [])
                  if str(a.get("ts", ""))[:10] == t.date().isoformat()
                  and a.get("decision") in ("ALERT", "ALERT_DRAFT"))
    if already >= cfg["max_alerts"]:
        row["decision"] = "BATCHED"
        row["note"] += f" | بلغ سقف التنبيهات اليومي ({cfg['max_alerts']}) — أُرجئ للبريف"
        events.append(("proactive_batched", {"pa_id": row["pa_id"], "reason": "rate_limit"}))
    elif _in_quiet(t, cfg) and not cand.get("override_quiet"):
        row["decision"] = "BATCHED"
        row["note"] += " | ساعات هدوء — أُرجئ للبريف التالي"
        events.append(("proactive_batched", {"pa_id": row["pa_id"], "reason": "quiet"}))
    else:
        quiet_override = bool(_in_quiet(t, cfg) and cand.get("override_quiet"))
        if quiet_override:
            row["quiet_override"] = True
        events.append(("proactive_alert", {"pa_id": row["pa_id"], "lane": row["lane"],
                                           "title": str(cand["title"])[:80],
                                           "quiet_override": quiet_override}))
    row["status"] = "DONE"


# ---------------------------------------------------------------- استدراك ما فات (Commitment Ledger)
def recovery_pass(S, t, cfg, events):
    """يقارن المتوقع بالفعلي؛ الفائت المهم لا يسقط بصمت أبدًا:
    ما فات ← الأثر ← خيارات الاستدراك ← تنفيذ داخلي مصرّح أو مسودة للاعتماد ← تقرير."""
    if not _enabled(S, "missed_recovery"):
        return
    today = t.date()
    for loop in S.get("open_loops", []):
        due = _as_date(loop.get("due"))
        if loop.get("status") != "OPEN" or not due or due >= today:
            continue
        loop["status"] = "MISSED"
        loop["updated_at"] = _marker(t)
        events.append(("proactive_missed", {"loop": loop["loop_id"],
                                            "title": str(loop["title"])[:80]}))
        days = (today - due).days
        if loop["kind"] == "they_promised":
            cat, risk, rev, hint = "external_comms", "medium", "reversible", "enqueue"
            body = (f"ما فات: ردّ {loop.get('owner')} على «{loop['title']}» متأخر {days} "
                    f"يومًا.\nالأثر: التبعية معطلة وتظهر كمن لا يتابع.\n"
                    "خيارات الاستدراك: 1) المسودة الجاهزة أدناه 2) تصعيد هاتفي "
                    "3) إعادة جدولة.\nما فعلت: جهّزت المسودة. ما أحتاج: اعتمادك بنقرة.\n"
                    f"المسودة: السلام عليكم، «{loop['title']}» تجاوز موعده بـ{days} "
                    "يومًا — أقدّر انشغالك؛ هل نثبّت موعدًا واقعيًا جديدًا؟ (عبدالرحمن)")
        elif loop["kind"] == "renewal":
            cat, risk, rev, hint = "money", "high", "irreversible", "enqueue"
            body = (f"ما فات: «{loop['title']}» استحق {due.isoformat()} ولم يُحسم.\n"
                    f"الأثر: تجديد تلقائي محتمل بكلفة "
                    f"{(loop.get('source') or {}).get('cost') or '—'} ريال/شهر.\n"
                    "خيارات الاستدراك: 1) سداد/تفاوض فوري 2) إلغاء قبل الغرامة.\n"
                    "ما فعلت: جهّزت التعليمة في طابور الاعتماد. ما أحتاج: قرارك بنقرة.")
        else:  # i_promised / decision / risk — استدراك داخلي قابل للعكس
            cat, risk, rev, hint = "reminders", "low", "reversible", "create_task"
            body = (f"ما فات: «{loop['title']}» تأخر {days} يومًا عن {due.isoformat()}.\n"
                    "الأثر: التزام مفتوح يستهلك انتباهك.\nخيارات الاستدراك: 1) نافذة "
                    "استدراك اليوم (حُجزت) 2) إعادة جدولة واقعية 3) حذف مُعلن.\n"
                    "ما فعلت: حجزت مهمة استدراك اليوم. ما أحتاج: 25 دقيقة منك.")
        cand = _cand(f"missed_recovery|{loop['loop_id']}|{today}", "missed_recovery",
                     "استدراك: " + str(loop["title"]), body, cat,
                     min(5, (loop.get("impact") or 3) + 1), _urg_from_days(0),
                     loop.get("confidence", 0.9), risk, rev, hint, due=today,
                     loop_id=loop["loop_id"],
                     override_quiet=(loop.get("impact") or 3) >= 4 and risk != "low",
                     action_type="recovery_" + loop["kind"])
        row = _apply_candidate(S, cand, t, cfg, events)
        loop["status"] = "RECOVERING"
        loop["recovery"] = {"pa_id": row["pa_id"], "decision": row["decision"],
                            "at": _marker(t)}


# ---------------------------------------------------------------- الحلقة الكاملة
def _mutate_sweep(S, t, cfg):
    changed = refresh_open_loops(S, t)
    if not S.get("standing_orders"):
        S["standing_orders"] = [dict(o) for o in DEFAULT_STANDING_ORDERS]
        changed = True
    summary = {"loops_open": 0, "act": 0, "prepare": 0, "alert": 0, "batched": 0,
               "suggest": 0, "skipped": 0, "missed": 0, "paused": False}
    paused_dt = _as_dt((S.get("manager_markers") or {}).get("proactive_paused_until"))
    if paused_dt and paused_dt > t:
        summary["paused"] = True
        return changed, (summary, [])
    events = []
    seen = {a.get("key") for a in S.get("proactive_actions", [])}
    for cand in sorted(collect_candidates(S, t, cfg), key=lambda c: -score(c)):
        if cand["key"] in seen:  # عدم تكرار اليوم نفسه — وما رُوجِع (UNDO) لا يُعاد
            summary["skipped"] += 1
            continue
        row = _apply_candidate(S, cand, t, cfg, events)
        changed = True
        seen.add(cand["key"])
        summary[{"ACT": "act", "PREPARE": "prepare", "ALERT": "alert",
                  "ALERT_DRAFT": "alert", "BATCHED": "batched",
                  "SUGGEST": "suggest"}.get(row["decision"], "skipped")] += 1
    before = len(S.get("proactive_actions", []))
    recovery_pass(S, t, cfg, events)
    changed = changed or len(S.get("proactive_actions", [])) != before
    summary["missed"] = sum(1 for l in S.get("open_loops", [])
                            if l.get("status") in ("MISSED", "RECOVERING"))
    summary["loops_open"] = sum(1 for l in S.get("open_loops", [])
                                if l.get("status") == "OPEN")
    return changed, (summary, events)


def sweep(store=None, now_dt=None, cfg=None, verbose=True):
    """دورة رصد كاملة داخل معاملة Store واحدة (write-on-change).

    دفع التنبيهات (تيليجرام) يحدث بعد إقفال المعاملة — القناة أثر خارجي اختياري
    لا يدخل في ذرّية الحالة، وفشل الشبكة لا يُسقط الدورة."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    t = now_dt or now()
    store = store or Store()
    summary, events = store.transaction(
        lambda S: _mutate_sweep(S, t, cfg), "proactive_sweep")
    for event, details in events:
        log_event(event, **details)
    if summary.get("paused"):
        if verbose:
            print("⏸️ الاستباقية موقوفة مؤقتًا — لم تُنفَّذ الدورة (resume للاستئناف).")
        return summary
    alert_ids = [d["pa_id"] for e, d in events if e == "proactive_alert"]
    alert_rows = [a for a in store.rows_all().get("proactive_actions", [])
                  if a.get("pa_id") in set(alert_ids)] if alert_ids else []
    summary["pushed"] = _push_alerts(t, events, alert_rows, verbose)
    if verbose:
        pushed = f" | دُفع تيليجرام={summary['pushed']}" if summary.get("pushed") else ""
        print(f"🛰️ دورة استباقية: حلقات مفتوحة={summary['loops_open']} | "
              f"نُفّذ={summary['act']} | جهّز={summary['prepare']} | "
              f"تنبيه={summary['alert']} | أُرجئ={summary['batched']} | "
              f"اقتراح={summary['suggest']} | فائت تحت الاستدراك={summary['missed']}"
              f"{pushed}")
    return summary


# ---------------------------------------------------------------- تعلّم: تراجع/تغذية/إيقاف
def pause(hours=4.0, store=None):
    store = store or Store()
    until = (now() + dt.timedelta(hours=hours)).isoformat(timespec="minutes")

    def mutate(S):
        markers = dict(S.get("manager_markers") or {})
        markers["proactive_paused_until"] = until
        S["manager_markers"] = markers
        return True, until

    result = store.transaction(mutate, "proactive_pause")
    log_event("proactive_pause", until=result)
    return result


def resume(store=None):
    store = store or Store()

    def mutate(S):
        markers = dict(S.get("manager_markers") or {})
        if "proactive_paused_until" not in markers:
            return False, None
        markers.pop("proactive_paused_until")
        S["manager_markers"] = markers
        return True, None

    store.transaction(mutate, "proactive_resume")
    log_event("proactive_resume")


def undo(pa_id, store=None):
    """زر التراجع: كل تنفيذ أخضر يحمل حمولة undo حرفية تُطبَّق هنا موثَّقة."""
    store = store or Store()

    def mutate(S):
        row = next((a for a in S.get("proactive_actions", [])
                    if a.get("pa_id") == pa_id), None)
        if not row:
            raise ValueError(f"لا يوجد إجراء استباقي بالمعرف {pa_id}")
        if row.get("status") == "UNDONE":
            return False, (False, "مُراجَع سابقًا — ولن يعيده المحرك (متعلَّم)")
        op = (row.get("undo") or {}).get("op")
        if op is None:
            return False, (False, "لا حمولة تراجع لهذا النوع (المسودات أصلًا بانتظار اعتمادك)")
        if op == "remove_task":
            before = len(S.get("tasks", []))
            S["tasks"] = [x for x in S.get("tasks", [])
                          if x.get("المصدر") != "proactive:" + pa_id]
            undone = before - len(S["tasks"])
        else:
            raise ValueError(f"عملية تراجع غير معروفة: {op}")
        row["status"] = "UNDONE"
        row["undone_at"] = now().isoformat(timespec="seconds")
        return True, (True, undone)

    result = store.transaction(mutate, "proactive_undo", pa_id=pa_id)
    log_event("proactive_undo", pa_id=pa_id)
    return result


def add_feedback(pa_id_or_kind, signal, scope="kind", store=None):
    """good ← تثبيت. much ← خفض للبريف 14 يومًا. never ← إيقاف النوع/الفئة
    (الأحمر الحرج يتجاوزها لحمايتك، موثَّقًا)."""
    assert signal in ("good", "much", "never")
    store = store or Store()
    S_all = store.rows_all()
    row = next((a for a in S_all.get("proactive_actions", [])
                if a.get("pa_id") == pa_id_or_kind), None)
    if row is not None:
        target = row.get("kind") if scope == "kind" else row.get("category")
    else:
        target = pa_id_or_kind  # تغذية مباشرة على نوع محفز أو فئة
    until = (now().date() + dt.timedelta(days=DEFAULT_CFG["demote_days"])).isoformat() \
        if signal == "much" else None

    def mutate(S):
        S.setdefault("proactive_feedback", []).append(
            {"target": target, "pa_id": row.get("pa_id") if row else None,
             "signal": signal, "scope": scope, "until": until,
             "at": now().isoformat(timespec="seconds")})
        return True, target

    result = store.transaction(mutate, "proactive_feedback")
    log_event("proactive_feedback", target=result, signal=signal, scope=scope)
    return result


def set_order(order_id, enabled_flag, store=None):
    store = store or Store()

    def mutate(S):
        for o in S.get("standing_orders", []):
            if o.get("order_id") == order_id:
                o["enabled"] = enabled_flag
                return True, o["name"]
        raise ValueError(f"لا يوجد أمر دائم بالمعرف {order_id}")

    name = store.transaction(mutate, "proactive_order",
                             order=order_id, enabled=enabled_flag)
    log_event("proactive_order", order=order_id, enabled=enabled_flag)
    return name


# ---------------------------------------------------------------- البريف الاستباقي
def render_brief(store=None, now_dt=None, cfg=None, reports_dir=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    t = now_dt or now()
    store = store or Store()
    out_dir = reports_dir or REPORTS
    today = t.date().isoformat()
    S = store.rows_all()
    rows_today = [a for a in S.get("proactive_actions", [])
                  if str(a.get("ts", ""))[:10] == today]
    done_keys = {a.get("key") for a in rows_today}
    cands = [c for c in sorted(collect_candidates(S, t, cfg), key=lambda c: -score(c))
             if c["key"] not in done_keys][:3]
    acts = [a for a in rows_today if a["decision"] == "ACT"]
    preps = [a for a in rows_today if a["decision"] in ("PREPARE", "ALERT_DRAFT")]
    alerts = [a for a in rows_today if a["decision"] in ("ALERT", "ALERT_DRAFT")]
    batched = [a for a in rows_today if a["decision"] == "BATCHED"]
    suggests = [a for a in rows_today if a["decision"] == "SUGGEST"]
    missed = [l for l in S.get("open_loops", []) if l.get("status") in ("MISSED", "RECOVERING")]
    paused_until = (S.get("manager_markers") or {}).get("proactive_paused_until")
    lines = [f"# 🛰️ البريف الاستباقي — {today}",
             "",
             f"> نفّذتُ عنك **{len(acts)}** إجراءً آمنًا قابلًا للتراجع، وجهّزتُ "
             f"**{len(preps)}** مسودة تنتظر نقرتك، ورفعتُ **{len(alerts)}** تنبيهًا مستعجلًا.",
             "", "## 🎯 أهم 3 متوقعة الآن"]
    if cands:
        for i, c in enumerate(cands, 1):
            lines.append(f"{i}. **{c['title']}** — أثر {c['impact']} × استعجال "
                         f"{c['urgency']} × ثقة {c['confidence']} (نقاط {score(c)}) "
                         f"← {c['category']}/{c['reversibility']}")
    else:
        lines.append("لا شيء عالق — كل الحلقات تحت السيطرة. ✅")
    if acts:
        lines += ["", "## ✅ ما فعلته دون أن تطلب (قابل للتراجع)"]
        for a in acts:
            lines.append(f"- [{a['pa_id']}] {a['title']} — تراجع: "
                         f"`python3 engine/proactive.py undo {a['pa_id']}`")
    if alerts:
        lines += ["", "## ⛔ تنبيهات حمراء/مستعجلة — انتباهك الآن"]
        for a in alerts:
            lines.append(f"- **{a['title']}** — {a['note']}")
    if preps:
        lines += ["", "## ✋ مسودات تنتظر اعتمادك بنقرة واحدة"]
        for a in preps:
            aq = (a.get("result") or {}).get("action_id")
            if aq:
                lines.append(f"- [{a['pa_id']}] {a['title']} ← اعتماد: "
                             f"`python3 engine/approve.py approve {aq} --hash <البصمة>`")
    if missed:
        lines += ["", "## 🔄 ما فات وما يُستدرك — لن يُسقَط شيء مهم بصمت"]
        for l in missed[:5]:
            rec = l.get("recovery") or {}
            lines.append(f"- «{l['title']}» — فات {l.get('due')} | استدراك "
                         f"{rec.get('pa_id', 'جارٍ')} ({rec.get('decision', '—')})")
    if batched or suggests:
        lines += ["", "## 💡 مؤجَّل لهذا البريف (تجنبًا للإزعاج)"]
        for a in (batched + suggests)[:6]:
            lines.append(f"- {a['title']} ({a['kind']})")
    paused_dt = _as_dt(paused_until)
    lines += ["", "## ⚙️ حالة الحواجز",
              f"- تنبيهات فورية اليوم: {len(alerts)}/{cfg['max_alerts']} · ساعات الهدوء: "
              f"{cfg['quiet_start']}–{cfg['quiet_end']} · "
              + ("⏸️ موقوفة حتى " + str(paused_until)
                 if paused_dt and paused_dt > t else "▶️ فعّالة"),
              "- الأوامر الدائمة الفعّالة: "
              f"{sum(1 for o in S.get('standing_orders', []) if o.get('enabled'))}"
              f"/{len(S.get('standing_orders', []))}",
              "- علّمني: `python3 engine/proactive.py feedback PA-xxxx good|much|never`"]
    md = "\n".join(lines) + "\n"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"proactive-brief-{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    def mutate(state):
        # date تُقرأ ككائن بعد parse_dates — قارن كسلسلة لضمان استبدال اليوم نفسه
        briefs = [b for b in state.get("proactive_briefs", [])
                  if str(b.get("date")) != today]
        briefs.append({"date": today, "path": os.path.relpath(path, BASE),
                       "acts": len(acts), "prepares": len(preps),
                       "alerts": len(alerts), "missed": len(missed)})
        state["proactive_briefs"] = briefs
        return True, None

    store.transaction(mutate, "proactive_brief", date=today)
    log_event("proactive_brief", date=today, acts=len(acts),
              prepares=len(preps), alerts=len(alerts), missed=len(missed))
    return path


# ---------------------------------------------------------------- الحالة
def status(store=None):
    store = store or Store()
    S = store.rows_all()
    t = now()
    today = t.date().isoformat()
    rows_today = [a for a in S.get("proactive_actions", [])
                  if str(a.get("ts", ""))[:10] == today]
    paused_until = (S.get("manager_markers") or {}).get("proactive_paused_until")
    paused_dt = _as_dt(paused_until)
    return {
        "enabled": enabled(),
        "paused_until": paused_until if paused_dt and paused_dt > t else None,
        "quiet_now": _in_quiet(t, DEFAULT_CFG),
        "telegram_push": telegram_push_status(),
        "alerts_today": sum(1 for a in rows_today
                            if a["decision"] in ("ALERT", "ALERT_DRAFT")),
        "max_alerts": DEFAULT_CFG["max_alerts"],
        "orders": {o["order_id"]: o.get("enabled") for o in S.get("standing_orders", [])},
        "open_loops": sum(1 for l in S.get("open_loops", []) if l.get("status") == "OPEN"),
        "recovering": sum(1 for l in S.get("open_loops", [])
                          if l.get("status") in ("MISSED", "RECOVERING")),
        "ledger_rows": len(S.get("proactive_actions", [])),
        "feedback": len(S.get("proactive_feedback", [])),
    }


def enabled():
    return os.environ.get("PROACTIVE_ENABLED", "1") != "0"


def push_test():
    """يرسل رسالة تجريبية عبر قناة التنبيه المستعجل نفسها للتحقق من التهيئة."""
    status = telegram_push_status()
    if status != "ready":
        return 1, status
    ok = _telegram_send("🛰️ تجربة قناة التنبيه الاستباقي — التوصيل يعمل.\n"
                        "(للإيقاف: PROACTIVE_TELEGRAM_PUSH=0)")
    log_event("proactive_push_test", ok=bool(ok))
    return (0, "sent") if ok else (1, "telegram_rejected")


def main():
    ap = argparse.ArgumentParser(description="محرك الاستباقية — Proactive Chief of Staff")
    ap.add_argument("cmd", choices=["sweep", "brief", "status", "orders", "matrix",
                                    "order-enable", "order-disable", "pause", "resume",
                                    "undo", "feedback", "push-test"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("signal", nargs="?", choices=["good", "much", "never"])
    ap.add_argument("--hours", type=float, default=4.0)
    ap.add_argument("--scope", choices=["kind", "category"], default="kind")
    args = ap.parse_args()

    try:
        if args.cmd == "sweep":
            sweep()
        elif args.cmd == "brief":
            print("🛰️ بريف استباقي: "
                  + os.path.relpath(render_brief(), BASE))
        elif args.cmd == "status":
            print(json.dumps(status(), ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "orders":
            S = Store().rows_all()
            if not S.get("standing_orders"):
                print("لم تُزرع الأوامر الدائمة بعد — شغّل: python3 engine/proactive.py sweep")
            for o in S.get("standing_orders", []):
                print(f"{'🟢' if o.get('enabled') else '⚪'} {o['order_id']} "
                      f"[{o['category']}/{o['level']}] {o['name']}")
        elif args.cmd == "matrix":
            for cat, lvl in AUTONOMY_MATRIX.items():
                print(f"{cat:15s} {lvl}  {LEVEL_AR[lvl]}")
        elif args.cmd in ("order-enable", "order-disable"):
            name = set_order(args.id, args.cmd == "order-enable")
            state = "فعّال" if args.cmd == "order-enable" else "موقوف"
            print(f"✅ {args.id} → {state} — {name}")
        elif args.cmd == "pause":
            print(f"⏸️ توقفت الاستباقية حتى {pause(args.hours)}")
        elif args.cmd == "resume":
            resume()
            print("▶️ عادت الاستباقية للعمل.")
        elif args.cmd == "undo":
            changed, info = undo(args.id)
            print(f"↩️ {args.id}: {'رُوجع — ' + str(info) + ' عنصر' if changed else info}")
        elif args.cmd == "feedback":
            target = add_feedback(args.id, args.signal, args.scope)
            print(f"🧠 سُجّلت تغذيتك «{args.signal}» على {target} — سأتعلم منها.")
        elif args.cmd == "push-test":
            code, why = push_test()
            if code == 0:
                print("✅ أُرسلت رسالة تجريبية إلى المحادثة المالكة — القناة تعمل.")
            else:
                print(f"❌ قناة الدفع غير جاهزة ({why}). اضبط TELEGRAM_BOT_TOKEN و"
                      "TELEGRAM_ALLOWED_CHAT_ID (أو تحدث مع البوت خاصة أولًا).")
            raise SystemExit(code)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

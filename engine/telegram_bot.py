# -*- coding: utf-8 -*-
"""
Telegram Approval Inbox + Chief of Staff Bot — بلا اعتماديات خارجية (urllib فقط).
الوظائف: بريف فوري · طابور الاعتماد بأزرار (مربوط بالبصمة C2) · حل طلبات القرار ·
مراجعات التعلّم · باب اليوم · التقاط أي نص إلى صندوق يومك · إشعارات تلقائية بالمستجدات.

التهيئة (دقيقتان — راجع docs/telegram-setup.md):
  1) @BotFather ← /newbot ← خذ التوكن
  2) شغّل البوت وأرسل /start من جوالك — أول محادثة تملك القناة (من بعدها: أي معرف آخر يُرفض ويُسجل أمنيًا)
  3) TELEGRAM_BOT_TOKEN=xxx python3 engine/telegram_bot.py

اختبار بدون تفعيل:  python3 engine/telegram_bot.py --test
"""
import datetime as dt
import glob
import json
import os
import sys
import re
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_FILE = os.path.join(BASE, "data", ".telegram-owner")
MARKERS = os.path.join(BASE, "data", ".telegram-markers.json")
API = f"https://api.telegram.org/bot{TOKEN}"


def api(method, _timeout=25, **params):
    if not TOKEN:
        return None
    data = json.dumps(params).encode()
    req = urllib.request.Request(API + "/" + method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=_timeout).read())
    except Exception as e:
        log_event("telegram_error", method=method, error=str(e)[:120])
        return None


# ---------------------------------------------------------------- الأمان: مالك واحد
def owner_id():
    try:
        return open(OWNER_FILE).read().strip()
    except Exception:
        return ""


def authorized(chat_id):
    return owner_id() == "" or str(chat_id) == owner_id()


def claim_or_verify(chat_id):
    """أول محادثة تملك القناة — ما بعدها يُرفض ويوثق أمنيًا."""
    if owner_id() == "":
        open(OWNER_FILE, "w").write(str(chat_id))
        log_event("telegram_owner_claimed", chat=str(chat_id))
        return True, True
    return (str(chat_id) == owner_id()), False


# ---------------------------------------------------------------- عارضات الحالة
def brief_text():
    files = sorted(glob.glob(os.path.join(BASE, "reports", "daily-brief-*.md")), reverse=True)
    if files:
        txt = open(files[0], encoding="utf-8").read()
        return "🌅 أحدث بريف:\n\n" + txt[:3500] + ("\n…(النسخة الكاملة في اللوحة)" if len(txt) > 3500 else "")
    return "لا بريف بعد — شغّل python3 engine/manager.py full"


def tasks_text():
    S = Store().rows_all()
    op = [t for t in S["tasks"] if t.get("الحالة") != "منجزة"]
    op.sort(key=lambda t: {"عالية": 0, "متوسطة": 1}.get(t.get("الأولوية"), 2))
    lines = [f"• [{t.get('الأولوية')}] {t['العنوان'][:60]}" for t in op[:8]]
    return "📋 أهم المهام المفتوحة:\n" + "\n".join(lines) + f"\n(الإجمالي: {len(op)})"


def decisions_keyboard():
    S = Store().rows_all()
    drs = [d for d in S.get("decision_requests", []) if d["status"] == "PENDING"]
    if not drs:
        return "لا طلبات قرار مفتوحة ✅", None
    kb = []
    lines = []
    for d in drs[:4]:
        lines.append(f"🧭 {d['id']}: {d['title'][:80]}\nالمهلة {str(d.get('deadline'))[:10]}")
        row = [{"text": f"{chr(65+i)} ✅ {d['id']}", "callback_data": f"dr:{d['id']}:{i+1}"} for i in range(len(d["options"][:3]))]
        kb.append(row)
    return "\n\n".join(lines), {"inline_keyboard": kb}


def approvals_keyboard():
    S = Store().rows_all()
    pend = [a for a in S["action_queue"] if a["status"] == "PENDING_APPROVAL"]
    if not pend:
        return "لا إجراءات بانتظار الاعتماد ✅", None
    kb, lines = [], []
    for a in pend[:5]:
        lines.append(f"🛂 {a['action_id']} [{a['type']}]\n{a['content'][:220]}…\n(ينتهي {a['expires_at']})")
        kb.append([{"text": f"✅ اعتماد {a['action_id']}", "callback_data": f"ap:{a['action_id']}:{a['content_hash'][:8]}"},
                   {"text": f"❌ رفض {a['action_id']}", "callback_data": f"rj:{a['action_id']}"}])
    return "\n\n".join(lines), {"inline_keyboard": kb}


def reviews_text():
    S = Store().rows_all()
    due = [r for r in S.get("learning_reviews", []) if r["status"] in ("DUE", "PRESENTED")]
    if not due:
        return "لا مراجعات مستحقة اليوم ✅"
    return "📚 مراجعات اليوم:\n" + "\n".join(f"• {r['concept_title']} ({r['est_minutes']} د) — {r['review_id']}" for r in due[:4]) + \
        "\nبعد الإجابة أرسل: /answer " + due[0]["review_id"] + " 85"


def door_text():
    try:
        from chief_of_staff import WEEK_DOORS  # خريطة الأبواب من المحرك نفسه
    except Exception:
        # نسخة محلية للطوارئ — نفس القيم في chief_of_staff.py (تعمل على حالة فارغة)
        WEEK_DOORS = {6: ("افتتاح الأسبوع + القيادة والإدارة", "خطة 30 دقيقة + Lean + تفويض مهمتين"),
                      0: ("الأعمال والمال", "عقود وعملاء وE-S-B-I — نافذة المفاوضات"),
                      1: ("العلاج الطبيعي العميق", "حالة تعليمية موثقة + بحث الكتف — قبل ذروة الظهر"),
                      2: ("الذكاء الاصطناعي والمشاريع", "30 دقيقة تطوير وكيل + خطوة مشروع"),
                      3: ("الإبداع والمحتوى + المراجعة التنفيذية", "مخرج منشور + مراجعة الأسبوع"),
                      4: ("الروحانية والعائلة 🛡️", "يوم محمي — لا عمل إلا بريف أخضر خفيف"),
                      5: ("التعلم العميق والخلوة", "LP-002/LP-003 + خلوة + تحضير الأسبوع")}
    t = dt.date.today()
    d = WEEK_DOORS.get(t.weekday(), ("—", ""))
    return f"🚪 باب اليوم ({t.isoformat()}): {d[0]}\n{d[1]}"


# ---------------------------------------------------------------- v0.9 — لوحة Master OS
def _mo_store():
    from store import Store
    return Store().rows_all()


def masteros_text():
    """🧭 ملخص بنية Master OS من الحالة الفعلية (أوامر تيليجرام v0.9)."""
    try:
        import scheduler
        canonical = len(scheduler.JOB_SPECS)
    except Exception:  # noqa: BLE001
        canonical = None
    S = _mo_store()
    tree = (S.get("drive_tree") or [{}])[0]
    pend = len([a for a in S.get("action_queue", [])
                if a.get("status") == "PENDING_APPROVAL"])
    folders = len(tree.get("folders", [])) if tree else 0
    sched = len(S.get("automation_schedule", [])) or canonical or 0
    return "\n".join([
        "🧭 Master OS — v0.9 (لوحة سريعة)",
        f"📁 شجرة Drive: {tree.get('root', 'Abdulrahman_Master_OS')} · {folders} مجلدات نطاق",
        f"🤖 وكلاء فرعيون: {len(S.get('sub_agents', []))} · 🎬 قنوات: {len(S.get('content_sources', []))}",
        f"🗺️ خرائط ذهنية: {len(S.get('mind_maps', []))} · 🎧 ملخصات: {len(S.get('audio_digests', []))}",
        f"⏰ وظائف مجدولة: {sched} · 🏃 تشغيلات: {len(S.get('automation_runs', []))}",
        f"⏳ بانتظار اعتمادك: {pend}",
        "",
        "الأوامر: /schedule · /mindmaps · /digests · /run · /today-actions · /masteros",
    ])


def schedule_text():
    """⏰ الجدول المعياري مع تمييز المستحق اليوم (بتوقيت الرياض)."""
    try:
        import datetime as _dt
        import scheduler
    except Exception as exc:  # noqa: BLE001
        return f"تعذر قراءة الجدول: {exc}"
    today = _dt.datetime.now(scheduler.TZ).date()
    end = _dt.datetime.combine(today, _dt.time(23, 59), tzinfo=scheduler.TZ)
    lines = ["⏰ محرك الأتمتة — Master OS (الرياض):"]
    for r in scheduler.JOB_SPECS:
        due = scheduler.is_due(r, end)
        tag = "✅ اليوم" if due else "   "
        when = r["time"]
        if r["cadence"] == "weekly":
            when += f" — {scheduler.AR_DAYS[r['weekday']]}"
        elif r["cadence"] == "monthly":
            when += (" — آخر يوم" if r.get("month_rule") == "last"
                     else f" — يوم {r.get('day_of_month')}")
        if r["cadence"] == "daily" and r.get("weekdays") == [6, 0, 1, 2, 3]:
            when += " (أحد–خميس)"
        lines.append(f"{tag} {r['emoji']} {when} — {r['name']}")
    if not any(scheduler.is_due(r, end) for r in scheduler.JOB_SPECS):
        lines.append("\n(لا وظائف اليوم — عطلة أو خارج النوافذ)")
    return "\n".join(lines)


def maps_text():
    """🗺️ أحدث الخرائط الذهنية من المكتبة."""
    S = _mo_store()
    rows = sorted(S.get("mind_maps", []), key=lambda m: str(m.get("created_at", "")), reverse=True)
    if not rows:
        return "لا خرائط بعد — شغّل: python3 engine/mindmap.py demo"
    lines = ["🗺️ مكتبة الخرائط الذهنية:"]
    kinds = {"audio-digest:lecture": "محاضرة", "audio-digest:youtube": "فيديو",
             "audio-digest:book": "كتاب", "audio-digest:article": "مقال",
             "audio-digest:podcast": "بودكاست", "system-reference": "مرجع النظام",
             "training-material": "مادة تدريبية", "book": "كتاب", "lecture": "محاضرة",
             "notes": "ملاحظات", "learning": "مصدر تعلم"}
    for m in rows[:8]:
        wk = " (أسبوعية)" if m.get("weekly") else ""
        kind = kinds.get(m.get("source_kind", ""), m.get("source_kind", ""))
        lines.append(f"• {m['map_id']} {m['title'][:60]}{wk} — {kind} — {m.get('status')}")
    return "\n".join(lines)


def digests_text():
    """🎧 حالة خط الملخصات الصوتية."""
    S = _mo_store()
    rows = S.get("audio_digests", [])
    if not rows:
        return "لا ملخصات بعد — queue ثم process (راجع docs/v0.9-master-os.md)"
    ar = {"QUEUED": "في الطابور", "DIGESTED": "جاهز (سكربت+خريطة)", "NARRATED": "بصوت"}
    lines = ["🎧 الملخصات الصوتية:"]
    for d in reversed(rows[-8:]):
        lines.append(f"• {d['digest_id']} [{ar.get(d.get('status'), d.get('status'))}] "
                     f"{d['title'][:55]} — خريطة {d.get('map_id') or '—'}")
    return "\n".join(lines)


def run_text():
    """تنفيذ الوظائف المجدولة المستحقة الآن — يولّد مسودات اعتماد فقط (لا إرسال)."""
    try:
        import scheduler
        n, s = scheduler.dispatch_due()
    except Exception as exc:  # noqa: BLE001
        return f"❌ فشل التنفيذ: {str(exc)[:200]}"
    if n == 0 and s == 0:
        return "⏰ لا وظائف مستحقة الآن — الجدول: /schedule"
    return f"⚙️ نُفّذ الآن: {n} مسودة جديدة في طابور الاعتماد · {s} بلا جديد.\nراجعها: /approve"


def diag_text():
    """🔗 حالة قنوات الربط من بيئة التشغيل (وجود المتغيرات فقط — بلا قيم ولا شبكة)."""
    try:
        if BASE not in sys.path:
            sys.path.insert(0, BASE)
        from connectors import connection_setup
        rows = connection_setup.run(live=False)
        icons = {"ok": "✅", "partial": "⚠️", "missing": "❌", "invalid": "❌"}
        lines = ["🔗 حالة القنوات (بيئة التشغيل):"]
        for r in rows:
            lines.append(f"{icons.get(r['status'], '❓')} {r['name']}: {r['status']}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"تعذر الفحص: {str(exc)[:200]}"


def today_actions_text():
    """إدراج «إجراءات اليوم» الثلاثة الفورية كمسودات (idempotent)."""
    try:
        import scheduler
        n = scheduler.today_actions()
    except Exception as exc:  # noqa: BLE001
        return f"❌ {str(exc)[:200]}"
    return ("✅ أُدرجت إجراءات اليوم (تكليف DHS 17 سبتمبر · إغلاق NEEDS_INPUT · "
            "تفعيل الصوت/الخرائط) — راجعها: /approve" if n else
            "🔁 إجراءات اليوم موجودة أصلًا — راجعها: /approve")


# ---------------------------------------------------------------- محرك الاستباقية v1.0
def proactive_text():
    """🛰️ ملخص محرك الاستباقية: الحالة، القناة، الحواجز، الحلقات المفتوحة."""
    try:
        import proactive
        st = proactive.status()
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذر جمع حالة الاستباقية: {str(exc)[:200]}"
    push_icons = {"ready": "✅ جاهزة", "no_token": "❌ بلا توكن",
                  "no_chat_id": "⚠️ بلا معرف محادثة", "disabled_env": "⏸️ موقوفة بالبيئة"}
    if not st["enabled"]:
        state = "⛔ معطّل (PROACTIVE_ENABLED=0)"
    elif st["paused_until"]:
        state = "⏸️ موقوف حتى " + str(st["paused_until"])
    else:
        state = "▶️ فعّال"
    orders_on = sum(1 for v in st["orders"].values() if v)
    return "\n".join([
        "🛰️ محرك الاستباقية",
        f"الحالة: {state} · هدوء الآن: {'نعم' if st['quiet_now'] else 'لا'}",
        f"قناة التنبيه المستعجل: {push_icons.get(st['telegram_push'], st['telegram_push'])}",
        f"تنبيهات اليوم: {st['alerts_today']}/{st['max_alerts']} · "
        f"حلقات مفتوحة: {st['open_loops']} · تحت الاستدراك: {st['recovering']}",
        f"أوامر دائمة فعّالة: {orders_on}/{len(st['orders'])} · "
        f"دفتر الإجراءات: {st['ledger_rows']} · تغذية مسجلة: {st['feedback']}",
        "الأوامر: /sweep دورة فورية · /proactive_test تجربة القناة · /approve الاعتمادات"])


def sweep_text():
    """يشغّل دورة استباقية فورية (write-on-change) ويعيد ملخصها."""
    try:
        import proactive
        summary = proactive.sweep(verbose=False)
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذرت الدورة: {str(exc)[:200]}"
    if summary.get("paused"):
        return "⏸️ الاستباقية موقوفة مؤقتًا — استئنفها من الطرفية: resume"
    tail = f"\n📨 دُفع لتيليجرام: {summary['pushed']}" if summary.get("pushed") else ""
    return ("🛰️ دورة استباقية اكتملت:\n"
            f"حلقات مفتوحة {summary['loops_open']} · نُفّذ {summary['act']} · "
            f"جهّز {summary['prepare']} · تنبيه {summary['alert']} · "
            f"أُرجئ {summary['batched']} · اقتراح {summary['suggest']} · "
            f"فائت تحت الاستدراك {summary['missed']}" + tail +
            "\nالمسودات: /approve · الحالة: /proactive")


def proactive_test_text():
    """يرسل رسالة تجريبية عبر قناة التنبيه المستعجل نفسها ويعيد الحكم."""
    try:
        import proactive
        code, why = proactive.push_test()
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذر الاختبار: {str(exc)[:200]}"
    if code == 0:
        return ("✅ نجح اختبار قناة التنبيه — رسالة «🛰️ تجربة» تصلك الآن من المسار "
                "نفسه الذي تسلكه التنبيهات الحمراء. إن وصلتك فهذه المحادثة جاهزة 100%.")
    reasons = {"no_token": "TELEGRAM_BOT_TOKEN غير مضبوط في بيئة التشغيل",
               "no_chat_id": "لا معرف محادثة — اضبط TELEGRAM_ALLOWED_CHAT_ID أو أرسل /start هنا أولًا",
               "disabled_env": "القناة موقوفة يدويًا (PROACTIVE_TELEGRAM_PUSH=0)"}
    return "❌ القناة غير جاهزة: " + reasons.get(why, why)


# ---------------------------------------------------------------- التوقيت التلقائي v1.1
def _args(text, index=1):
    """الوسيط رقم index من رسالة الأمر ("" عند الغياب)."""
    parts = (text or "").split()
    return parts[index] if len(parts) > index else ""


def timing_text():
    """🕰️ بطاقة التوقيت التلقائي: ما المجدول، متى جرى آخر مرة، والقادم."""
    try:
        import timing
        return timing.status_text()
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذر جمع حالة التوقيت: {str(exc)[:200]}"


def timing_run_text(which=""):
    """يشغّل ما استحق الآن (أو وظيفة بعينها) من الجوال — مسودات وقاية، لا إرسال."""
    try:
        import timing
    except Exception as exc:  # noqa: BLE001
        return f"❌ محرك التوقيت غير متاح: {str(exc)[:200]}"
    which = (which or "").strip().lower()
    try:
        if which in ("", "tick", "now"):
            out = timing.tick(verbose=False, trigger="telegram")
            if out["status"] == "idle":
                return "⏰ لا شيء مستحق الآن — الجدول يعمل. الحالة: /timing"
            if out["status"] == "busy":
                return "🔒 دورة توقيت أخرى تعمل الآن — أعد المحاولة بعد لحظة."
            if out["status"] == "disabled":
                return "⏸️ التوقيت التلقائي معطّل (AIOS_TIMING_ENABLED=0)."
            lines = [f"🕰️ نُفّذ {len(out.get('ran', []))} من وظائف الجدولة الآن:"]
            for res in out.get("ran", []):
                lines.append(f"{'✅' if res['status'] == 'ok' else '❌'} {res['job_id']}"
                             f" — {res.get('reason', '—')}")
            return "\n".join(lines) + "\nالمسودات: /approve"
        if which not in ("brief", "sweep", "review"):
            return "صيغة: /timing_run [brief|sweep|review] — أو /timing_run وحدها للمستحق الآن"
        res = timing.run_job(which, force=True, verbose=False, trigger="telegram")
        icon = "✅" if res["status"] == "ok" else "❌"
        return (f"{icon} {res['job_id']} → {res['status']}\n"
                "المسودات: /approve · البريف: reports/proactive-brief-*.md")
    except ValueError as exc:
        return f"❌ {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذر التنفيذ: {str(exc)[:200]}"


def weekly_review_text(days=7):
    """📊 مراجعة الأسبوع الاستباقية: قبولك/رفضك الحقيقي + التوصية بالعتبات."""
    try:
        import proactive
        return proactive.review_text(days=days) + \
            "\n\nللتطبيق التلقائي من الطرفية: python3 engine/proactive.py review --apply"
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذرت المراجعة الأسبوعية: {str(exc)[:200]}"


def goals_text_inline():
    """🔬 بطاقة أهداف البحث: المسجَّل، المستحق الآن، وحالة كل كبسولة."""
    try:
        import research_goals
        return research_goals.goals_text()
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذرت قراءة أهداف البحث: {str(exc)[:200]}"


def goal_add_text(rest):
    """يسجّل هدفًا من الجوال بإعدادات افتراضية (أسبوعي أحد 05:40 · deep)."""
    rest = (rest or "").strip().strip('"').strip()
    if len(rest) < 6:
        return ('❌ صيغة: /goal_add <نص الهدف>\n'
                'مثال: /goal_add أفكار محتوى من أسئلة جمهور إعادة التأهيل')
    try:
        import research_goals
        changed, row, path = research_goals.add_goal(rest)
    except Exception as exc:  # noqa: BLE001
        return f"❌ تعذر تسجيل الهدف: {str(exc)[:200]}"
    if not changed:
        return (f"ℹ️ الهدف مسجّل مسبقًا: {row['goal_id']} — «{row.get('goal')}»\n"
                f"   حالته: {row.get('status') or 'لم تُشغَّل'} · {path}")
    try:
        import timing as _tg          # مصدر الحقيقة الوحيد لأسماء الأيام (قاموس بالفهرس)
        day = _tg.AR_DAYS.get(int(row["weekday"]) % 7, "")
    except Exception:  # noqa: BLE001
        day = ""
    return (f"✅ {row['goal_id']} مسجّل · {row['cadence']} {day} {row['at']} "
            f"· {row['mode']}\n   الهيكل: {path}\n"
            "   المحرك لا يتصفّح: املأ الهيكل من جلسة بحث خارجية، أو من الطرفية:\n"
            "   python3 engine/research_goals.py attach "
            f"{row['goal_id']} <ملف>")


# ---------------------------------------------------------------- معالجات
def handle(msg):
    chat = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    ok, claimed = claim_or_verify(chat)
    if not ok:
        api("sendMessage", chat_id=chat, text="⛔ هذه قناة مملوكة — غير مصرح لك.")
        log_event("telegram_unauthorized_access", chat=chat, text=text[:60])
        return
    if claimed:
        api("sendMessage", chat_id=chat, text="✅ تم ربط جوالك بالنظام — أنت المالك. جرّب: /brief")
        return

    if text.startswith("/brief"):
        api("sendMessage", chat_id=chat, text=brief_text())
    elif text.startswith("/tasks"):
        api("sendMessage", chat_id=chat, text=tasks_text())
    elif text.startswith("/decisions"):
        t, kb = decisions_keyboard()
        api("sendMessage", chat_id=chat, text=t, reply_markup=kb)
    elif text.startswith("/approve"):
        t, kb = approvals_keyboard()
        api("sendMessage", chat_id=chat, text=t, reply_markup=kb)
    elif text.startswith("/reviews"):
        api("sendMessage", chat_id=chat, text=reviews_text())
    elif text.startswith("/door"):
        api("sendMessage", chat_id=chat, text=door_text())
    elif text.startswith("/masteros"):
        api("sendMessage", chat_id=chat, text=masteros_text())
    elif text.startswith("/schedule"):
        api("sendMessage", chat_id=chat, text=schedule_text())
    elif text.startswith("/mindmaps"):
        api("sendMessage", chat_id=chat, text=maps_text())
    elif text.startswith("/digests"):
        api("sendMessage", chat_id=chat, text=digests_text())
    elif text.startswith("/run"):
        api("sendMessage", chat_id=chat, text=run_text())
    elif text.startswith("/today-actions"):
        api("sendMessage", chat_id=chat, text=today_actions_text())
    elif text.startswith("/diag"):
        api("sendMessage", chat_id=chat, text=diag_text())
    elif text.startswith("/proactive_test"):
        api("sendMessage", chat_id=chat, text=proactive_test_text())
    elif text.startswith("/proactive"):
        api("sendMessage", chat_id=chat, text=proactive_text())
    elif text.startswith("/sweep"):
        api("sendMessage", chat_id=chat, text=sweep_text())
    elif text.startswith("/goal_add"):
        api("sendMessage", chat_id=chat, text=goal_add_text(text.partition(" ")[2] if " " in text else ""))
    elif text.startswith("/goals"):
        api("sendMessage", chat_id=chat, text=goals_text_inline())
    elif text.startswith("/timing_run"):
        api("sendMessage", chat_id=chat, text=timing_run_text(_args(text)))
    elif text.startswith("/timing"):
        api("sendMessage", chat_id=chat, text=timing_text())
    elif text.startswith("/review") and not text.startswith("/reviews"):
        parts = text.split()
        try:
            days = max(1, int(parts[1]))
        except (IndexError, ValueError):
            days = 7
        api("sendMessage", chat_id=chat, text=weekly_review_text(days))
    elif text.startswith("/mastery"):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(BASE, "engine", "learning_engine.py"), "mastery"],
                           capture_output=True, text=True)
        api("sendMessage", chat_id=chat, text="🗺️ خريطة الإتقان:\n" + (r.stdout or "—")[:3000])
    elif text.startswith("/answer"):
        parts = text.split()
        try:
            rid, score = parts[1], int(parts[2])
            from learning_engine import cmd_answer
            cmd_answer(rid, score)
            api("sendMessage", chat_id=chat, text=f"✅ سُجلت {rid} = {score}%")
        except SystemExit:
            raise
        except Exception as e:
            api("sendMessage", chat_id=chat, text=f"صيغة: /answer LR-001 85\n{e}")
    elif text.startswith("/help") or text.startswith("/start"):
        api("sendMessage", chat_id=chat, text=("الأوامر:\n/brief البريف • /tasks المهام • /decisions القرارات بأزرار\n"
                                               "/approve الاعتمادات بأزرار • /reviews مراجعات اليوم • /answer LR-001 85\n"
                                               "/door باب اليوم • /mastery خريطة الإتقان • /okr الأهداف\n"
                                               "🧭 Master OS (v0.9):\n"
                                               "/masteros ملخص البنية • /schedule الجدول • /mindmaps الخرائط\n"
                                               "/digests الملخصات الصوتية • /run تنفيذ المستحق الآن • /today-actions إجراءات اليوم\n"
                                               "/diag حالة قنوات الربط\n"
                                               "🛰️ v1.1 (الاستباقي + التوقيت التلقائي):\n"
                                               "/proactive حالة المحرك • /sweep دورة فورية • /timing حالة الجدولة\n"
                                               "/timing_run [brief|sweep|review] تشغيل المستحق الآن • /review مراجعة الأسبوع\n"
                                               "🔬 v1.2 (أهداف البحث — بلا تصفّح): /goals حالة الأهداف • /goal_add <نص> تسجيل هدف\n"
                                               "وأي نص ترسله = يُلتقط في صندوق يومك تلقائيًا 📥"))
    elif text and re.match(r"^طاق[هة]?\s*(\d{1,2}).*ارهاق", text.replace("إرهاق", "ارهاق")):
        m = re.match(r"^طاق[هة]?\s*(\d{1,2}).*ارهاق\s*(\d{1,2})", text.replace("إرهاق", "ارهاق"))
        if m and 1 <= int(m.group(1)) <= 10 and 1 <= int(m.group(2)) <= 10:
            from energy_log import log as elog
            elog(int(m.group(1)), int(m.group(2)), "من تيليجرام")
            api("sendMessage", chat_id=chat, text="🔋 سُجل — تعافيك يُقاس الآن")
        else:
            api("sendMessage", chat_id=chat, text="صيغة: طاقة 7 إرهاق 3 (من 1 إلى 10)")
    elif text.startswith("/okr"):
        import subprocess
        args = text.split()[1:]
        r = subprocess.run([sys.executable, os.path.join(BASE, "engine", "okr.py")] + args,
                           capture_output=True, text=True)
        api("sendMessage", chat_id=chat, text=(r.stdout or r.stderr or "—")[:1500])
    elif msg.get("voice") or msg.get("document") or msg.get("audio"):
        import csv as _csv
        inbox = os.path.join(BASE, "data", "inbox.csv")
        new = not os.path.exists(inbox)
        with open(inbox, "a", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            if new: w.writerow(["التصنيف","العنوان","النوع","الأولوية","الموعد","ملاحظة"])
            w.writerow(["مهمة", "🎙️ رسالة صوتية/ملف من تيليجرام — يحتاج تفريغًا", "قسم", "متوسطة", "", dt.date.today().isoformat()])
        log_event("TELEGRAM_VOICE_CAPTURED")
        api("sendMessage", chat_id=chat, text="🎙️ وصلت — سُجلت في صندوق يومك (التفريغ النصي مرحلة قادمة؛ أرسل نصها لاحقًا إن استعجلت)")
    else:
        # التقاط: أي نص → صندوق اليوم (يُصنف عند الاستيراد)
        import csv as _csv
        inbox = os.path.join(BASE, "data", "inbox.csv")
        new = not os.path.exists(inbox)
        with open(inbox, "a", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            if new:
                w.writerow(["التصنيف", "العنوان", "النوع", "الأولوية", "الموعد", "ملاحظة"])
            w.writerow(["مهمة", text[:120], "قسم", "متوسطة", "", f"من تيليجرام {dt.date.today()}"])
        log_event("TELEGRAM_CAPTURED", chars=len(text))
        api("sendMessage", chat_id=chat, text="📥 التُقط في صندوق يومك — سيُصنف مع الدورة القادمة")


def handle_callback(cb):
    chat = str(cb["message"]["chat"]["id"])
    if not authorized(chat):
        api("answerCallbackQuery", callback_query_id=cb["id"], text="⛔ غير مصرح")
        return
    data = cb["data"]
    if data.startswith("ap:"):
        _, aid, h8 = data.split(":")
        st = Store(); S = st.rows_all()
        act = next((a for a in S["action_queue"] if a["action_id"] == aid), None)
        if not act or act["status"] != "PENDING_APPROVAL":
            api("answerCallbackQuery", callback_query_id=cb["id"], text="غير متاح")
            return
        if act["content_hash"][:8] != h8:  # قاعدة C2: الاعتماد مربوط بالبصمة
            act["status"] = "REJECTED"; st.commit(S, "telegram_hash_mismatch", action=aid)
            log_event("approval_denied", action_id=aid, reason="telegram_hash_mismatch")
            api("answerCallbackQuery", callback_query_id=cb["id"], text="❌ بصمة غير مطابقة — رُفض")
            return
        act["status"] = "APPROVED"; act["approved_at"] = dt.date.today().isoformat()
        st.commit(S, "telegram_approved", action=aid)
        log_event("action_approved", action_id=aid, via="telegram")
        api("answerCallbackQuery", callback_query_id=cb["id"], text=f"✅ {aid} اعتُمد")
        api("sendMessage", chat_id=chat, text=f"✅ {aid} معتمد — نفّذ المحتوى من صفحة الاعتماد ثم: python3 engine/approve.py executed {aid}")
    elif data.startswith("rj:"):
        _, aid = data.split(":", 1)
        st = Store(); S = st.rows_all()
        act = next((a for a in S["action_queue"] if a["action_id"] == aid), None)
        if act and act["status"] == "PENDING_APPROVAL":
            act["status"] = "REJECTED"
            st.commit(S, "telegram_rejected", action=aid)
            log_event("action_rejected", action_id=aid, via="telegram")
        api("answerCallbackQuery", callback_query_id=cb["id"], text=f"🚫 {aid} رُفض")
    elif data.startswith("dr:"):
        _, did, opt = data.split(":")
        from manager import resolve_dr
        try:
            resolve_dr(did, int(opt), note="من تيليجرام")
            api("answerCallbackQuery", callback_query_id=cb["id"], text=f"✅ {did} حُسم")
        except SystemExit:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="تعذر الحسم")
        except Exception as e:
            api("answerCallbackQuery", callback_query_id=cb["id"], text=str(e)[:120])


# ---------------------------------------------------------------- إشعارات المستجدات
def markers():
    try:
        return json.load(open(MARKERS))
    except Exception:
        return {}


def notify_new():
    """يدفع الجديد إلى مالك القناة: إجراءات معلقة لم تُبلغ + بريف الصباح."""
    own = owner_id()
    if not own or not TOKEN:
        return
    m = markers()
    S = Store().rows_all()
    changed = False
    for a in S["action_queue"]:
        if a["status"] == "PENDING_APPROVAL" and not a.get("notified"):
            t, kb = None, None
            kb = {"inline_keyboard": [[
                {"text": "✅ اعتماد", "callback_data": f"ap:{a['action_id']}:{a['content_hash'][:8]}"},
                {"text": "❌ رفض", "callback_data": f"rj:{a['action_id']}"}]]}
            res = api("sendMessage", chat_id=int(own),
                       text=f"🛂 إجراء جديد بانتظارك: {a['action_id']}\n{a['content'][:250]}…\nينتهي: {a['expires_at']}",
                       reply_markup=kb)
            if res and res.get("ok"):
                a["notified"] = True
                changed = True
    if changed:
        st = Store(); st.data["action_queue"] = [a for a in Store().data["action_queue"]]
        # نعيد الكتابة بأمان عبر rows_all
        st2 = Store(); S2 = st2.rows_all()
        for a2 in S2["action_queue"]:
            for a in S["action_queue"]:
                if a2["action_id"] == a["action_id"] and a.get("notified"):
                    a2["notified"] = True
        st2.commit(S2, "telegram_notified")
    # بريف الصباح (6–9 صباحًا، مرة يوميًا)
    now = dt.datetime.now()
    if 6 <= now.hour < 9 and m.get("brief_day") != now.date().isoformat():
        api("sendMessage", chat_id=int(own), text=brief_text()[:3500])
        m["brief_day"] = now.date().isoformat()
        json.dump(m, open(MARKERS, "w"))


# ---------------------------------------------------------------- الحلقة
def run():
    if not TOKEN:
        print("⚠️ عيّن المتغير: TELEGRAM_BOT_TOKEN — راجع docs/telegram-setup.md")
        return
    print("🤖 بوت النظام يعمل (polling) — Ctrl+C للإيقاف")
    offset = markers().get("offset", 0)
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=30, _timeout=40)
            for u in (res or {}).get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
                elif "callback_query" in u:
                    handle_callback(u["callback_query"])
            m = markers(); m["offset"] = offset; json.dump(m, open(MARKERS, "w"))
            notify_new()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log_event("telegram_loop_error", error=str(e)[:120])
            time.sleep(5)


def test():
    """اختبار المنطق بلا شبكة — يتحقق أن كل العارضات تعمل على الحالة الحقيقية."""
    print("── وضع الاختبار (بلا شبكة) ──")
    print(door_text()); print()
    print(tasks_text()[:200] + "…"); print()
    print(reviews_text()); print()
    t, kb = decisions_keyboard()
    print(t[:200])
    if kb:
        print("لوحة القرارات: موجودة ✅")
    else:
        print("لوحة القرارات: لا طلبات مفتوحة (طبيعي على حالة فارغة)")
    t2, kb2 = approvals_keyboard()
    print(f"الاعتمادات المعلقة المعروضة: {'موجودة' if kb2 else 'لا شيء'}")
    print(masteros_text()); print()
    print(schedule_text()[:600] + "…"); print()
    print(maps_text()[:300]); print()
    print(digests_text()[:300]); print()
    print(diag_text())
    print("✅ كل العارضات واللوحات سليمة")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    else:
        run()

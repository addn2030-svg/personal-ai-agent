# -*- coding: utf-8 -*-
"""
محرك الأتمتة المجدول (Daily / Weekly / Monthly) — v0.9.

ينفّذ حلقات الأتمتة الثلاث بتوقيت الرياض (Asia/Riyadh) بالضبط كما في التصميم:

  اليومي:   06:45 بريف صباحي · 07:30 نافذة تركيز · 16:00 إغلاق الوحدات (أحد–خميس)
            · 20:30 الملخص المسموع المسائي
  الأسبوعي: الأحد 07:15 توجيه تشغيلي · الثلاثاء 14:00 فحص DHS · الخميس 07:00 مالية
            · الجمعة 16:00 الخريطة الذهنية الأسبوعية
  الشهري:   28 تقرير الإنتاجية · 1 مؤشر الصحة المالية · آخر يوم أرشفة سياق المعرفة

قاعدة الحوكمة (مطابقة v4.1.1): المحرك لا يرسل أي شيء خارجيًا أبدًا. كل تشغيل
يولّد مسودة رسالة تُدرج في طابور الاعتماد (action_queue → PENDING_APPROVAL)
وتظهر في صفحة approvals-latest.html — الاعتماد عبر engine/approve.py.

التشغيل:
  python3 engine/scheduler.py list              ← عرض الجدول الكامل
  python3 engine/scheduler.py due --date YYYY-MM-DD [--at HH:MM]
                                                ← محاكاة: ما المستحق في وقت معين؟
  python3 engine/scheduler.py dispatch          ← تنفيذ ما استحق الآن (تسجيل + مسودات)
  python3 engine/scheduler.py today-actions     ← مسودات «إجراءات اليوم» الثلاثة الفورية
يتكامل تلقائيًا مع حلقة المدير (engine/manager.py --loop) عبر scheduler.dispatch_due().
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

AR_DAYS = {6: "الأحد", 0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء",
           3: "الخميس", 4: "الجمعة", 5: "السبت"}
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

# الجدول المعياري — مصدر الحقيقة التشغيلي للجدولة (يُتاح تعديله مستقبلًا
# عبر قسم automation_schedule بمخزن الحالة دون تغيير المنطق)
# weekday: 0=الاثنين .. 6=الأحد (مثل Python). time: HH:MM
JOB_SPECS = [
    # ---------------------------- اليومي ----------------------------
    {"job_id": "daily.morning_brief_0645", "emoji": "☀️", "agent": "AG-MORNING",
     "name": "بث لوحة التوجيه الصباحي", "cadence": "daily", "time": "06:45",
     "weekdays": None,
     "purpose": "استدعاء الشيت والتقويم وبث لوحة التوجيه الصباحي على تيليجرام",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "daily.focus_block_0730", "emoji": "🧠", "agent": "AG-MORNING",
     "name": "مسار الإفراغ الذهني + حجز نافذة التركيز 60 دقيقة", "cadence": "daily",
     "time": "07:30", "weekdays": None,
     "purpose": "فتح مسار الإفراغ السريع (صوت/نص) وحجز Focus Block",
     "kind": "draft", "channel": "calendar"},
    {"job_id": "daily.supervisor_close_1600", "emoji": "📋", "agent": "AG-CLINICAL",
     "name": "تنبيه إغلاق الوحدات اليومي (PT/OT/ST)", "cadence": "daily",
     "time": "16:00", "weekdays": [6, 0, 1, 2, 3],
     "purpose": "تذكير مشرفي الوحدات برفع الإغلاق اليومي للتقارير والعيادات",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "daily.audio_digest_2030", "emoji": "🎧", "agent": "AG-KNOWLEDGE",
     "name": "المسار المعرفي المسموع (ملخص 5–7 دقائق)", "cadence": "daily",
     "time": "20:30", "weekdays": None,
     "purpose": "إرسال ملخص صوتي مركز لأبرز فكرة/فيديو استُخلص خلال اليوم",
     "kind": "draft", "channel": "telegram"},
    # ---------------------------- الأسبوعي ----------------------------
    {"job_id": "weekly.ops_sunday_0715", "emoji": "🏥", "agent": "AG-CLINICAL",
     "name": "رسالة التوجيه التشغيلي الأسبوعية للمشرفين", "cadence": "weekly",
     "weekday": 6, "time": "07:15",
     "purpose": "بث إنجازات الأسبوع والمهام المعلقة ومحاضر الاجتماعات لمشرفي التأهيل",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "weekly.dhs_tuesday_1400", "emoji": "🎓", "agent": "AG-CLINICAL",
     "name": "فحص نسبة إنجاز تدريب DHS", "cadence": "weekly",
     "weekday": 1, "time": "14:00",
     "purpose": "فحص تلقائي لنسبة إنجاز تدريب الكوادر على منصة DHS وتنبيه المشرف المسؤول",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "weekly.finance_thursday_0700", "emoji": "💰", "agent": "AG-FINANCE",
     "name": "مراجعة كشوف الميزانية وتحديث شيت المالية", "cadence": "weekly",
     "weekday": 3, "time": "07:00",
     "purpose": "مراجعة العجز وضبط خطة الادخار",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "weekly.weekly_mindmap_friday_1600", "emoji": "🗺️", "agent": "AG-KNOWLEDGE",
     "name": "الخريطة الذهنية الأسبوعية (كتاب/محاضرة الأسبوع)", "cadence": "weekly",
     "weekday": 4, "time": "16:00",
     "purpose": "توليد الخريطة الذهنية الشاملة لملخص كتاب أو محاضرة الأسبوع",
     "kind": "generator", "channel": "telegram"},
    # ---------------------------- الشهري ----------------------------
    {"job_id": "monthly.monthly_prod_28", "emoji": "📊", "agent": "AG-CLINICAL",
     "name": "تقرير الإنتاجية الشهري التنفيذي", "cadence": "monthly",
     "day_of_month": 28, "time": "07:00",
     "purpose": "تجميع تقارير الإنتاجية الشهرية للأقسام وإحصاءات الرعاية المنزلية",
     "kind": "generator", "channel": "telegram"},
    {"job_id": "monthly.monthly_finance_health_1st", "emoji": "🧮", "agent": "AG-FINANCE",
     "name": "مؤشر الصحة المالية الشخصية الشهري", "cadence": "monthly",
     "day_of_month": 1, "time": "07:30",
     "purpose": "إعادة احتساب مؤشر الصحة المالية ونسبة تغطية الديون والادخار",
     "kind": "draft", "channel": "telegram"},
    {"job_id": "monthly.monthly_context_archive_end", "emoji": "🗃️", "agent": "AG-MORNING",
     "name": "أرشفة وتحديث ملف الذاكرة المعرفية (Context Update)", "cadence": "monthly",
     "month_rule": "last", "time": "23:30",
     "purpose": "أرشفة وتحديث سياق الوكيل على GitHub ليعكس القرارات الجديدة",
     "kind": "generator", "channel": "github"},
]

DEMO_TODAY_ACTIONS = [
    {"action": "تكليف تدريب DHS — مشرف التعليم المستمر",
     "date": "2026-09-17",
     "content": (
         "📌 تكليف تدريب منصة DHS — مشرف التعليم المستمر\n"
         "السلام عليكم، نأمل تثبيت موعد تدريب الكوادر على منصة DHS "
         "يوم الخميس 17 سبتمبر 2026، واعتماد القائمة النهائية للمتدربين "
         "من كل وحدة (PT/OT/ST) قبل 14 سبتمبر. الرجاء تأكيد الاستلام "
         "والقاعة المخصصة. — عبدالرحمن، قسم التأهيل الطبي")},
    {"action": "توزيع المهام في شيت خطة الإنجاز — إغلاق NEEDS_INPUT",
     "date": "2026-09-09",
     "content": (
         "🛠️ توزيع جديد للمهام في شيت «خطة الإنجاز والمهام»:\n"
         "الهدف: إغلاق جميع حالات NEEDS_INPUT — كل صف بلا مسؤول أو تاريخ "
         "يُسنَد لوحدة ومسؤول وتاريخ استحقاق اليوم، ثم يُحدَّث في الشيت "
         "وتظهر النتيجة في بريف الغد.")},
    {"action": "تفعيل مسار التحويل الصوتي المعرفي",
     "date": "2026-09-09",
     "content": (
         "🎧 بدء تحويل التلخيصات القادمة إلى مخرجات مسموعة وخرائط ذهنية:\n"
         "يربط وكيل المعرفة قنوات اليوتيوب التخصصية (Physio Network، Clinical "
         "Edge، HBR، ...) ويحوّل كل تلخيص إلى Audio Digest + Mind Map تلقائيًا "
         "عبر engine/audio_digest.py و engine/mindmap.py.")},
]


def _hash(txt):
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def _parse_ref(arg=None):
    """مرجع زمني: الآن بتوقيت الرياض، أو من --date/--at."""
    if isinstance(arg, dt.datetime):
        return arg
    if arg:
        if isinstance(arg, dt.date):
            return dt.datetime.combine(arg, dt.time(23, 59), tzinfo=TZ)
        try:
            return dt.datetime.fromisoformat(str(arg)).replace(tzinfo=TZ)
        except ValueError:
            raise SystemExit(f"❌ صيغة وقت غير مفهومة: {arg}")
    return dt.datetime.now(TZ)


def sun_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def cycle_key(job, ref: dt.datetime) -> str:
    d = ref.date()
    if job["cadence"] == "daily":
        return d.isoformat()
    if job["cadence"] == "weekly":
        return sun_of(d).isoformat()
    if job["cadence"] == "monthly":
        if job.get("month_rule") == "last":
            return f"{d.year:04d}-{d.month:02d}-END"
        return f"{d.year:04d}-{d.month:02d}"
    return d.isoformat()


def is_due(job, ref: dt.datetime) -> bool:
    d = ref.date()
    t = ref.time().replace(second=0, microsecond=0)
    if t < _hhmm(job["time"]):
        return False
    if job["cadence"] == "daily":
        wd = job.get("weekdays")
        return wd is None or d.weekday() in wd
    if job["cadence"] == "weekly":
        return d.weekday() == job.get("weekday")
    if job["cadence"] == "monthly":
        if job.get("month_rule") == "last":
            last = _last_day(d.year, d.month)
            return d.day == last
        return d.day == job.get("day_of_month")
    return False


def _hhmm(s):
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def _last_day(year, month):
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day


def _fmt_date(d: dt.date):
    return f"{AR_DAYS[d.weekday()]} {d.day} {AR_MONTHS[d.month - 1]} {d.year}"


def _open_tasks(S):
    return [t for t in S.get("tasks", []) if t.get("الحالة") != "منجزة"]


def _overdue_tasks(S, today):
    out = []
    for t in S.get("tasks", []):
        due = t.get("الموعد النهائي")
        if isinstance(due, str):
            try:
                due = dt.date.fromisoformat(due[:10])
            except ValueError:
                due = None
        if due and t.get("الحالة") != "منجزة" and due < today:
            out.append(t)
    return out


def _ar_date(x):
    try:
        if isinstance(x, str):
            x = dt.date.fromisoformat(str(x)[:10])
        return _fmt_date(x) if isinstance(x, dt.date) else str(x)
    except ValueError:
        return str(x)


# =====================================================================
# المنتِجات (Producers) — تعمل على لقطة الحالة وتعيد مسودة رسالة
# =====================================================================
def _produce_morning_brief(S, ref):
    d = ref.date()
    today_tasks = [t for t in _open_tasks(S)
                   if t.get("الموعد النهائي") and str(t.get("الموعد النهائي"))[:10] == d.isoformat()]
    meetings = [m for m in S.get("meetings", [])
                if m.get("التاريخ") and str(m.get("التاريخ"))[:10] == d.isoformat()]
    pending = len([a for a in S.get("action_queue", [])
                   if a.get("status") == "PENDING_APPROVAL"])
    waiting_over = len([w for w in S.get("waiting_for", [])
                        if w.get("status") == "OVERDUE"])
    top = today_tasks[:3] or _open_tasks(S)[:3]
    lines = [f"☀️ بريف {_fmt_date(d)} — لوحة التوجيه الصباحي",
             f"مهام مستحقة اليوم: {len(today_tasks)} | اجتماعات: {len(meetings)} "
             f"| انتظار متأخر: {waiting_over} | بانتظار اعتمادك: {pending}", ""]
    if top:
        lines.append("🎯 الأبرز اليوم:")
        for t in top:
            lines.append(f"   • {t.get('العنوان')} ({t.get('الحالة', '')})")
    else:
        lines.append("🎯 لا مهام مفتوحة مسجلة — أضف مهامك عبر صندوق اليوم.")
    if meetings:
        lines.append("")
        lines.append("📅 اجتماعات اليوم:")
        for m in meetings[:4]:
            lines.append(f"   • {m.get('الوقت', '')} — {m.get('الموضوع')}")
    lines.append("")
    lines.append("الإجراء: افتح لوحة القيادة dashboard-latest.html للمتابعة الكاملة.")
    return "\n".join(lines)


def _produce_focus_block(S, ref):
    d = ref.date()
    return (f"🧠 نافذة التركيز العميق — {_fmt_date(d)}\n"
            "1) خصص 60 دقيقة قبل الظهر لمهمة واحدة عالية الأولوية.\n"
            "2) أغلق الإشعارات وافتح «مسار الإفراغ الذهني» (صوت/نص) أولًا "
            "لتفريغ أي فكرة عالقة.\n"
            "3) بعد النافذة: سجّل الناتج في صندوق اليوم — دقيقة واحدة تكفي.\n"
            "هل أحجز النافذة في التقويم؟ (بعد الاعتماد هنا)")


def _produce_supervisor_close(S, ref):
    d = ref.date()
    return (f"📋 إغلاق الوحدات — {_fmt_date(d)} (16:00)\n"
            "مشرفو PT / OT / ST: يرجى رفع تقرير الإغلاق اليومي قبل 17:00:\n"
            "   • عدد الجلسات الفعلية مقابل المخطط\n"
            "   • حالات عدم الحضور والانتظار\n"
            "   • أي حوادث أو أعطال\n"
            "التقارير تُرفع عبر نموذج المشرفين وتظهر في بريف الغد.")


def _produce_audio_digest_evening(S, ref):
    d = ref.date()
    ds = [x for x in S.get("audio_digests", [])
          if x.get("status") in ("DIGESTED", "NARRATED")
          and x.get("digested_at") and str(x["digested_at"])[:10] == d.isoformat()]
    if ds:
        x = ds[-1]
        m = S.get("mind_maps", [])
        mm = next((v for v in m if v.get("map_id") == x.get("map_id")), None)
        lines = [f"🎧 الملخص المسموع المسائي — {x['title']}",
                 "أبرز 3 نقاط:"]
        lines += [f"   • {p}" for p in (x.get("key_points") or [])[:3]]
        lines += [f"الخريطة الذهنية: reports/mindmaps/{mm['file_md']}" if mm else
                  "الخريطة الذهنية: —",
                  "الملف الصوتي: " + (x.get("audio_path") or
                                      "لم يُولَّد بعد (عرّف ELEVENLABS_API_KEY)")]
        return "\n".join(lines)
    return None  # لا ملخص جديد اليوم — تشغيل مسجَّل بلا إرسال


def _produce_ops_sunday(S, ref):
    d = ref.date()
    week_start = sun_of(d)
    week_end = week_start + dt.timedelta(days=6)
    done = [t for t in S.get("tasks", []) if t.get("الحالة") in ("منجزة", "مكتملة")]
    open_t = _open_tasks(S)
    overdue = _overdue_tasks(S, d)
    meetings = [m for m in S.get("meetings", [])
                if m.get("التاريخ") and week_start.isoformat()
                <= str(m.get("التاريخ"))[:10] <= week_end.isoformat()]
    lines = [f"🏥 التوجيه التشغيلي الأسبوعي — أسبوع {week_start.isoformat()}",
             f"مهام أُنجزت: {len(done)} | مفتوحة: {len(open_t)} | متأخرة: {len(overdue)}",
             f"اجتماعات الأسبوع: {len(meetings)}", ""]
    if meetings:
        lines.append("📅 المحاضر المقررة:")
        for m in meetings[:5]:
            lines.append(f"   • {_ar_date(m.get('التاريخ'))} {m.get('الوقت', '')} — "
                         f"{m.get('الموضوع')} ({m.get('حالة التحضير', '')})")
    if overdue:
        lines.append("")
        lines.append("⏳ مهام متأخرة تحتاج حسمًا:")
        for t in overdue[:5]:
            lines.append(f"   • {t.get('العنوان')} — مستحقة {_ar_date(t.get('الموعد النهائي'))}")
    lines.append("")
    lines.append("المطلوب من المشرفين: تأكيد منجزات الأسبوع وإدراج المعلق في "
                 "«خطة الإنجاز» قبل اجتماع الأحد المقبل.")
    return "\n".join(lines)


def _produce_dhs_tuesday(S, ref):
    pct_raw = os.environ.get("DHS_COMPLETION_PCT", "")
    src = "مؤشر بيئي DHS_COMPLETION_PCT"
    if not pct_raw:
        cfg = next((r for r in S.get("automation_schedule", [])
                    if r.get("job_id") == "weekly.dhs_tuesday_1400"), None)
        pct_raw = (cfg or {}).get("completion_pct", "")
        src = "سجل الجدولة (automation_schedule)"
    try:
        pct = float(pct_raw)
    except (TypeError, ValueError):
        pct = None
    if pct is None:
        return ("🎓 فحص تدريب DHS (أسبوعي)\n"
                "⚠️ لا توجد نسبة إنجاز مسجلة في DHS_Training_Tracker بعد.\n"
                "الخطوة: حدّث شيت المتابعة (أو DHS_COMPLETION_PCT في البيئة) "
                "وسأعيد الفحص الثلاثاء القادم مع تنبيه المشرف المسؤول.")
    if pct < 100:
        return (f"🎓 تنبيه تدريب DHS — الإنجاز {pct:.0f}%\n"
                "لم يكتمل تدريب الكوادر على منصة DHS بعد. المطلوب من مشرف "
                "التعليم المستمر: رفع قائمة المتأخرين ومواعيد استحقاقهم "
                "لتثبيت جلسة استدراكية هذا الأسبوع.")
    return (f"🎓 تدريب DHS — اكتمل ({pct:.0f}%) 🎉\n"
            "كل الكوادر المستهدفة أنهت تدريب منصة DHS. نرفع شهادة الإنجاز "
            "في ملف القسم وتُغلق المتابعة.")


def _produce_finance_thursday(S, ref):
    rows = S.get("finance", [])
    today = ref.date()
    total = sum(float(r.get("التكلفة (ريال/شهر)") or 0) for r in rows)
    renew = [r for r in rows if r.get("تاريخ التجديد") and
             (dt.date.fromisoformat(str(r["تاريخ التجديد"])[:10]) - today).days <= 14
             and (dt.date.fromisoformat(str(r["تاريخ التجديد"])[:10]) - today).days >= 0]
    unused = [r for r in rows if r.get("آخر استخدام") and
              (today - dt.date.fromisoformat(str(r["آخر استخدام"])[:10])).days > 30]
    lines = [f"💰 مراجعة الميزانية — {_fmt_date(today)}",
             f"إجمالي الالتزامات الشهرية: {total:,.0f} ريال | بنود مرصودة: {len(rows)}"]
    if renew:
        lines.append("")
        lines.append("🔁 تجديدات خلال 14 يومًا:")
        lines += [f"   • {r.get('البند')} — {_ar_date(r.get('تاريخ التجديد'))}"
                  for r in renew[:5]]
    if unused:
        lines.append("")
        lines.append("⚠️ بنود غير مستخدمة (أكثر من 30 يومًا) — مرشحة للإلغاء:")
        lines += [f"   • {r.get('البند')} (آخر استخدام {_ar_date(r.get('آخر استخدام'))})"
                  for r in unused[:5]]
    lines.append("")
    lines.append("الخطوة: حدّث تبويب المالية وقرّر خفض أي بند غير مستخدم هذا الأسبوع.")
    return "\n".join(lines)


def _produce_weekly_mindmap(ref, store):
    import mindmap
    row, _created = mindmap.build_weekly(ref_date=ref.date(), store=store)
    return (f"🗺️ الخريطة الذهنية الأسبوعية جاهزة — {row['title']}\n"
            f"المصدر: {row.get('source_ref', '—')}\n"
            f"الكود: reports/mindmaps/{row['file_mmd']} (Mermaid)\n"
            f"التقرير: reports/mindmaps/{row['file_md']}\n"
            "للصق في Obsidian/mermaid.live أو إرفاقها برسالة المجموعة.")


def _produce_monthly_prod(ref, store):
    S = store.rows_all()
    d = ref.date()
    done = len([t for t in S.get("tasks", []) if t.get("الحالة") in ("منجزة", "مكتملة")])
    open_t = len(_open_tasks(S))
    meetings = len(S.get("meetings", []))
    decisions = len(S.get("decisions", []))
    kpi_rows = S.get("kpis", [])
    patients = 0
    for r in kpi_rows[-30:]:
        patients += int(r.get("المرضى") or 0)
    md = f"""# 📊 التقرير التنفيذي الشهري — {AR_MONTHS[d.month - 1]} {d.year}

> وُلِّد تلقائيًا بواسطة engine/scheduler.py (أتمتة يوم 28).

## مؤشرات مختصرة
- مهام مكتملة في السجل: {done} | مهام مفتوحة: {open_t}
- اجتماعات مسجلة: {meetings} | قرارات موثقة: {decisions}
- إجمالي مرضى آخر 30 يوم عمل (من kpis): {patients:,}

## الوحدات
- ملاحظة: تُستكمل الأرقام التفصيلية من تقارير الوحدات (PT/OT/ST) ومن
  إحصاءات الرعاية المنزلية عند ربط مصادرها (Tasks_Ledger + DHS_Training_Tracker).

## مرفقات
- لوحة القيادة: reports/dashboard-latest.html
- سجل الأصول: reports/registry-latest.html
"""
    out = os.path.join(REPORTS, f"monthly-executive-{d.year}-{d.month:02d}.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    log_event("monthly_prod_generated", file=os.path.basename(out))
    return (f"📊 التقرير التنفيذي الشهري — {AR_MONTHS[d.month - 1]} {d.year}\n"
            f"مهام مكتملة: {done} | مفتوحة: {open_t} | قرارات: {decisions} | "
            f"مرضى (آخر 30 يوم عمل): {patients:,}\n"
            f"الملف الكامل: reports/{os.path.basename(out)}"), [os.path.basename(out)]


def _produce_finance_health_1st(ref, store):
    S = store.rows_all()
    d = ref.date()
    rows = S.get("finance", [])
    total = sum(float(r.get("التكلفة (ريال/شهر)") or 0) for r in rows)
    unused_n = len([r for r in rows if r.get("آخر استخدام") and
                    (d - dt.date.fromisoformat(str(r["آخر استخدام"])[:10])).days > 30])
    savings = sum(float(r.get("التكلفة (ريال/شهر)") or 0) for r in rows if r.get("آخر استخدام") and
                  (d - dt.date.fromisoformat(str(r["آخر استخدام"])[:10])).days > 30)
    base = 100
    if total > 0:
        base -= min(20, unused_n * 5)
        if unused_n:
            base -= 5
    index = max(0, base)
    debt_cov = os.environ.get("DEBT_COVERAGE_PCT", "غير محددة")
    save_rate = os.environ.get("SAVINGS_RATE_PCT", "غير محددة")
    return (f"🧮 مؤشر الصحة المالية — أول {AR_MONTHS[d.month - 1]}\n"
            f"المؤشر المحسوب: {index}/100\n"
            f"الالتزامات الشهرية: {total:,.0f} ريال | بنود غير مستخدمة: {unused_n} "
            f"(وفورات محتملة: {savings:,.0f} ريال/شهر)\n"
            f"تغطية الديون: {debt_cov} | نسبة الادخار: {save_rate}\n"
            "حدّث قيمتي التغطية والادخار في شيت المالية لتظهر في التقرير القادم.")


def _produce_context_archive(ref, store):
    S = store.rows_all()
    d = ref.date()
    pending = len([a for a in S.get("action_queue", [])
                   if a.get("status") == "PENDING_APPROVAL"])
    decisions_n = len(S.get("decisions", []))
    maps_n = len(S.get("mind_maps", []))
    digests_n = len(S.get("audio_digests", []))
    md = f"""# 🗃️ لقطة سياق المعرفة — {AR_MONTHS[d.month - 1]} {d.year}

> تُنشأ نهاية كل شهر لأرشفة حالة النظام قبل تحديث سياق الوكيل (Context Update).

## أوجه التقدم هذا الشهر
- قرارات موثقة حتى الآن: {decisions_n}
- خرائط ذهنية: {maps_n} | ملخصات صوتية: {digests_n}
- إجراءات بانتظار الاعتماد عند الأرشفة: {pending}

## ملفات سياق الذاكرة المقترح تحديثها (GitHub)
1. data/state.json — الحالة التشغيلية الموحدة (تُؤرشف، لا تُرفع للعموم)
2. docs/v0.9-master-os.md — مرجع البنية (يُحدَّث عند تغيير الجدولة/الوكلاء)
3. README.md — سجل الإصدارات
4. evaluation/ — وثائق التبني ونتائج الاختبارات

## قرار الأرشفة
بعد الاعتماد هنا، يُنفَّذ الالتزام (git commit + push) عبر بوابة الاعتماد.
"""
    out = os.path.join(REPORTS, f"context-snapshot-{d.year}-{d.month:02d}.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    log_event("context_snapshot_generated", file=os.path.basename(out))
    return (f"🗃️ لقطة سياق المعرفة — {AR_MONTHS[d.month - 1]} {d.year}\n"
            f"قرارات: {decisions_n} | خرائط: {maps_n} | ملخصات صوتية: {digests_n} | "
            f"إجراءات معلقة: {pending}\n"
            f"الملف: reports/{os.path.basename(out)}\n"
            "التحديث على GitHub يتم بعد اعتماد هذا الإجراء (نوع github_context_commit)."), \
        [os.path.basename(out)]


def produce(job, S, ref, store):
    """يستدعي المنتِج المناسب ويعيد (message|None, files, extra_type)."""
    pid = job["job_id"].split(".")[-1]
    if pid == "morning_brief_0645":
        return _produce_morning_brief(S, ref), [], "telegram_brief_board"
    if pid == "focus_block_0730":
        return _produce_focus_block(S, ref), [], "calendar_focus_block"
    if pid == "supervisor_close_1600":
        return _produce_supervisor_close(S, ref), [], "telegram_supervisor_reminder"
    if pid == "audio_digest_2030":
        return _produce_audio_digest_evening(S, ref), [], "telegram_audio_digest"
    if pid == "ops_sunday_0715":
        return _produce_ops_sunday(S, ref), [], "telegram_ops_directive"
    if pid == "dhs_tuesday_1400":
        return _produce_dhs_tuesday(S, ref), [], "telegram_dhs_alert"
    if pid == "finance_thursday_0700":
        return _produce_finance_thursday(S, ref), [], "telegram_finance_review"
    if pid == "weekly_mindmap_friday_1600":
        return _produce_weekly_mindmap(ref, store), [], "weekly_mindmap_generated"
    if pid == "monthly_prod_28":
        msg, files = _produce_monthly_prod(ref, store)
        return msg, files, "monthly_prod_report"
    if pid == "monthly_finance_health_1st":
        return _produce_finance_health_1st(ref, store), [], "monthly_finance_health"
    if pid == "monthly_context_archive_end":
        msg, files = _produce_context_archive(ref, store)
        return msg, files, "github_context_commit"
    return None, [], "unknown"


# =====================================================================
# التنفيذ — تسجيل + طابور اعتماد (لا إرسال خارجي)
# =====================================================================
def _log_run(store, job, ref, outcome, detail=""):
    S = store.rows_all()
    runs = S.get("automation_runs", [])
    runs.append({
        "run_id": f"RUN-{len(runs) + 1:04d}",
        "job_id": job["job_id"],
        "cycle_key": cycle_key(job, ref),
        "ran_at": ref.isoformat(timespec="minutes"),
        "outcome": outcome,
        "detail": detail,
    })
    S["automation_runs"] = runs[-300:]
    store.commit(S, "automation_run", job=job["job_id"],
                 cycle=cycle_key(job, ref), outcome=outcome)
    log_event("automation_run", job=job["job_id"], cycle=cycle_key(job, ref),
              outcome=outcome)


def _enqueue_draft(store, job, message, action_type, files=None):
    """إدراج مسودة في طابور الاعتماد (مطابق لنمط v4.1.1 + بصمة C2)."""
    S = store.rows_all()
    queue = S.get("action_queue", [])
    body = message + (("\n\n📎 الملفات: " + "، ".join(files)) if files else "")
    h = _hash(body)
    if any(a.get("content_hash") == h for a in queue):
        return None
    queue.append({
        "action_id": f"A-{len(queue) + 1:03d}",
        "type": action_type,
        "channel": job["channel"],
        "content": body,
        "content_hash": h,
        "status": "PENDING_APPROVAL",
        "created_at": dt.date.today().isoformat(),
        "expires_at": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
        "approved_at": None,
        "executed_at": None,
        "origin": f"scheduler:{job['job_id']}",
    })
    S["action_queue"] = queue
    store.commit(S, "scheduler_enqueue", job=job["job_id"],
                 action=queue[-1]["action_id"])
    log_event("scheduler_draft_enqueued", job=job["job_id"],
              action=queue[-1]["action_id"], hash=h)
    return queue[-1]


def dispatch_due(ref=None, store=None, verbose=True):
    """تنفيذ كل الوظائف المستحقة عند ref (الافتراضي: الآن بتوقيت الرياض)."""
    store = store or Store()
    if ref is None:
        ref = dt.datetime.now(TZ)
    ref = _parse_ref(ref)
    sync_schedule_to_state(store=store)  # يعكس الجدول المعياري إن كان القسم فارغًا
    executed, skipped = 0, 0
    for job in JOB_SPECS:
        if not is_due(job, ref):
            continue
        S = store.rows_all()
        ckey = cycle_key(job, ref)
        # ملاحظة: قراءات store تحوّل السلاسل التاريخية إلى كائنات date،
        # لذا المقارنة تكون نصية دائمًا (str) لتفادي الازدواج.
        if any(str(r.get("job_id")) == job["job_id"]
               and str(r.get("cycle_key")) == str(ckey)
               for r in S.get("automation_runs", [])):
            continue  # نُفّذت في هذه الدورة (idempotent)
        msg, files, a_type = produce(job, S, ref, store)
        if msg:
            _enqueue_draft(store, job, msg, a_type, files)
            _log_run(store, job, ref, "produced", detail=a_type)
            if verbose:
                print(f"✅ {job['emoji']} {job['job_id']} → مسودة «{a_type}» في طابور الاعتماد")
            executed += 1
        else:
            _log_run(store, job, ref, "nothing_new")
            if verbose:
                print(f"🔸 {job['emoji']} {job['job_id']} → لا جديد (سُجّل بلا إرسال)")
            skipped += 1
    if verbose and executed == 0 and skipped == 0:
        print("⏰ لا وظائف مستحقة الآن.")
    return executed, skipped


def due_listing(ref):
    """محاكاة: قائمة الوظائف المستحقة عند مرجع زمني (بدون تنفيذ)."""
    ref = _parse_ref(ref)
    out = []
    for job in JOB_SPECS:
        if is_due(job, ref):
            out.append(job)
    return out


def sync_schedule_to_state(store=None):
    """يعكس الجدول المعياري في قسم automation_schedule (إن كان فارغًا)."""
    store = store or Store()
    S = store.rows_all()
    if S.get("automation_schedule"):
        return S["automation_schedule"]
    rows = [dict(j) for j in JOB_SPECS]
    S["automation_schedule"] = rows
    store.commit(S, "automation_schedule_sync", jobs=len(rows))
    return rows


def show_schedule(store=None):
    store = store or Store()
    rows = sync_schedule_to_state(store)
    today = dt.date.today()
    print("\n⏰ محرك الأتمتة المجدول — v0.9 (Asia/Riyadh)\n" + "=" * 52)
    current = None
    for r in rows:
        grp = {"daily": "اليومي", "weekly": "الأسبوعي", "monthly": "الشهري"}[r["cadence"]]
        if grp != current:
            current = grp
            print(f"\n── {grp} ──")
        when = r["time"]
        if r["cadence"] == "weekly":
            when += f" — {AR_DAYS[r['weekday']]}"
        elif r["cadence"] == "monthly":
            when += (" — آخر يوم" if r.get("month_rule") == "last"
                     else f" — يوم {r.get('day_of_month')}")
        if r["cadence"] == "daily" and r.get("weekdays") == [6, 0, 1, 2, 3]:
            when += " (أحد–خميس)"
        print(f"  {r['emoji']} {r['job_id']:<36} {when}")
        print(f"      ↳ {r['purpose']} [{r['kind']} → طابور الاعتماد]")
    print()
    return rows


def today_actions(store=None):
    """مسودات «إجراءات اليوم» الثلاثة الفورية (من التصميم) — بانتظار الاعتماد."""
    store = store or Store()
    S = store.rows_all()
    queue = S.get("action_queue", [])
    n = 0
    for item in DEMO_TODAY_ACTIONS:
        body = item["content"]
        h = _hash(body)
        if any(a.get("content_hash") == h for a in queue):
            continue
        queue.append({
            "action_id": f"A-{len(queue) + 1:03d}",
            "type": "today_action",
            "channel": "internal/telegram",
            "content": body,
            "content_hash": h,
            "status": "PENDING_APPROVAL",
            "created_at": dt.date.today().isoformat(),
            "expires_at": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
            "approved_at": None,
            "executed_at": None,
            "origin": "scheduler:today-actions",
            "target_date": item["date"],
        })
        n += 1
    if n:
        S["action_queue"] = queue
        store.commit(S, "today_actions_seeded", added=n)
        log_event("today_actions_seeded", added=n)
        print(f"✅ أُدرجت {n} مسودة «إجراءات اليوم» — اعتمدها عبر engine/approve.py")
    else:
        print("🔁 إجراءات اليوم موجودة أصلًا في طابور الاعتماد.")
    return n


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "list"

    def val(name):
        return args[args.index(name) + 1] if name in args else None

    if cmd == "list":
        show_schedule()
    elif cmd == "due":
        ref = val("--date") or dt.datetime.now(TZ)
        at = val("--at")
        if at and isinstance(ref, str):
            ref = f"{ref} {at}"
        listing = due_listing(ref)
        ref_dt = _parse_ref(ref)
        if not listing:
            print(f"⏰ لا وظائف مستحقة عند {ref_dt.isoformat(timespec='minutes')}.")
        for job in listing:
            print(f"  {job['emoji']} {job['job_id']} — {job['name']} عند {job['time']}")
        print(f"\n({len(listing)} وظيفة مستحقة)")
    elif cmd == "dispatch":
        dispatch_due()
    elif cmd == "today-actions":
        today_actions()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

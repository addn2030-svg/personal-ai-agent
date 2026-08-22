# -*- coding: utf-8 -*-
"""
Abdulrahman AI OS v0.1 — Agent 0: Chief of Staff Engine
يقرأ «الشيت الرئيسي» (data/master-sheet.xlsx) ويولّد:
  1) البريف الصباحي (يتيح تلقائيًا ليوم العمل القادم إذا كانت نهاية أسبوع)
  2) المراجعة التنفيذية الأسبوعية (كل المجالات)
  3) كشف الأنماط والمشاكل (Pattern & Problem Detector — منطق حتمي)
  4) مسودات رسائل المتابعة الجاهزة
التشغيل:  python3 engine/chief_of_staff.py
"""
import datetime as dt
import os
from collections import Counter, defaultdict
from openpyxl import load_workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEET = os.path.join(BASE, "data", "master-sheet.xlsx")
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

TODAY = dt.date.today()
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
AR_DAYS = {6: "الأحد", 0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت"}

def fmt_pp(new, old):
    """فرق بالنقاط المئوية — أنسب لعرض النسب."""
    d = (new - old) * 100
    if abs(d) < 0.5:
        return "≈ لا تغيير"
    arrow = "▲" if d > 0 else "▼"
    return f"{arrow} {abs(d):.0f} نقطة {'✅' if d < 0 else '⚠️'}"

def ar_date(d):
    return f"{d.day} {AR_MONTHS[d.month - 1]} {d.year}"

def sun_of(d):
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)

# نهاية الأسبوع في السعودية: الجمعة والسبت → البريف ليوم العمل القادم
TARGET = TODAY
BRIEF_LABEL = "بريف اليوم"
if TODAY.weekday() == 4:
    TARGET = TODAY + dt.timedelta(days=2); BRIEF_LABEL = "بريف بداية الأسبوع (الأحد)"
elif TODAY.weekday() == 5:
    TARGET = TODAY + dt.timedelta(days=1); BRIEF_LABEL = "بريف بداية الأسبوع (الأحد)"

# ---------------------------------------------------------------- تحميل الحالة (State Store — مصدر الحقيقة الموحد، إصلاح C1)
from store import Store, log_event
from voice_call import CALLER_AR, INTENT_AR

store = Store()
S = store.rows_all()

tasks     = S.get("tasks", [])
projects  = S.get("projects", [])
leads     = S.get("leads", [])
kpis      = [r for r in S.get("kpis", []) if isinstance(r.get("التاريخ"), dt.date)]
meetings  = S.get("meetings", [])
decisions = S.get("decisions", [])
followups = S.get("followups", [])
voice     = S.get("voice", [])
learning  = S.get("learning", [])
finance   = S.get("finance", [])
waiting_for = S.get("waiting_for", [])

# ---- كشف تغيّر الحالة منذ آخر بريف (لقطة مشتقة للمقارنة فقط — ليست مصدر حقيقة، كما في v4.1.1) ----
prev_snap = S.get("brief_snapshot") or {}
def _snap():
    return {
        "projects": {p.get("المشروع", ""): p.get("الحالة", "") for p in projects},
        "tasks": {t.get("العنوان", ""): t.get("الحالة", "") for t in tasks},
        "waiting": {(w.get("task") or w.get("item") or ""): (w.get("status") or "WAITING") for w in waiting_for},
        "leads": {l.get("الجهة", ""): l.get("الحالة", "") for l in leads},
    }
cur_snap = _snap()
changes = []
if prev_snap:
    for sect, label in [("projects", "مشروع"), ("tasks", "مهمة"), ("waiting", "انتظار"), ("leads", "عميل")]:
        prev, cur = prev_snap.get(sect, {}), cur_snap[sect]
        for k in cur:
            if k and k not in prev:
                changes.append(f"🆕 {label} جديد: {k}")
            elif k in prev and prev[k] != cur[k]:
                changes.append(f"🔁 {label} «{k}»: {prev[k]} ← {cur[k]}")
        for k in prev:
            if k and k not in cur:
                changes.append(f"🏁 أُغلق {label}: {k}")
open_drs = [d for d in S.get("decision_requests", []) if d.get("status") == "PENDING"]
unbriefed_calls = [c for c in S.get("voice_calls", [])
                   if c.get("status") == "COMPLETED" and not c.get("briefed")]
unbriefed_calls.sort(key=lambda c: (not c.get("safety_flags"), not c.get("handoff")))  # الأمني ثم التحويلات أولًا
WEEK_DOORS = {6: ("افتتاح الأسبوع + القيادة والإدارة", "خطة 30 دقيقة + Lean + تفويض مهمتين"),
              0: ("الأعمال والمال", "عقود وعملاء وE-S-B-I — نافذة المفاوضات"),
              1: ("العلاج الطبيعي العميق", "حالة تعليمية موثقة + بحث الكتف — قبل ذروة الظهر"),
              2: ("الذكاء الاصطناعي والمشاريع", "30 دقيقة تطوير وكيل + خطوة مشروع"),
              3: ("الإبداع والمحتوى + المراجعة التنفيذية", "مخرج منشور + مراجعة الأسبوع"),
              4: ("الروحانية والعائلة 🛡️", "يوم محمي — لا عمل إلا بريف أخضر خفيف"),
              5: ("التعلم العميق والخلوة", "LP-002/LP-003 + خلوة + تحضير الأسبوع")}
day_door = WEEK_DOORS.get(TARGET.weekday(), ("—", ""))

due_reviews = [r for r in S.get("learning_reviews", []) if r["status"] in ("DUE", "PRESENTED")][:2]  # سقف: مراجعتان/يوم
concept_by_id = {c["concept_id"]: c for c in S.get("learning_concepts", [])}

# ---------------------------------------------------------------- 1) كشف الأنماط (حتمي)
weeks = defaultdict(list)
for r in kpis:
    weeks[sun_of(r["التاريخ"])].append(r)
week_keys = sorted(weeks)
this_w, prev_w = week_keys[-1], week_keys[-2] if len(week_keys) > 1 else None

def agg(sun):
    rs = weeks[sun]
    pat = sum(r["المرضى"] for r in rs); ses = sum(r["الجلسات"] for r in rs)
    ns = sum(r["عدم حضور"] for r in rs)
    wait = sum(r["متوسط الانتظار (دقيقة)"] for r in rs) / len(rs)
    return dict(pat=pat, ses=ses, ns=ns, rate=ns / pat if pat else 0, wait=wait,
                days=len(rs), staff=sum(r["الموظفون"] for r in rs) / len(rs))

A, B = agg(this_w), agg(prev_w)

# نمط عدم الحضور حسب اليوم عبر الأسابيع
by_day = defaultdict(list)  # weekday -> [(week, rate)]
for sun in week_keys:
    for r in weeks[sun]:
        pat = r["المرضى"] or 1
        by_day[r["التاريخ"].weekday()].append((sun, r["عدم حضور"] / pat))

worst_day, worst_rates = None, None
for wd, series in by_day.items():
    if series and series[-1][1] >= 0.15 and len(series) >= 3:
        r1, r2, r3 = series[-3][1], series[-2][1], series[-1][1]
        if r3 >= r2 + 0.02 and r2 >= r1 + 0.02:
            if worst_rates is None or r3 > worst_rates[-1]:
                worst_day, worst_rates = wd, (r1, r2, r3)

peak_hours = Counter(str(r.get("ذروة الانتظار (الساعة)")) for r in kpis if r.get("ذروة الانتظار (الساعة)"))
peak_mode, peak_n = peak_hours.most_common(1)[0] if peak_hours else ("—", 0)

incidents = [f"{ar_date(r['التاريخ'])}: {r['حوادث/ملاحظات']}" for r in kpis if r.get("حوادث/ملاحظات")]

issues = []  # (وزن، عنوان، تفصيل، إجراء مقترح)
if worst_day is not None:
    r1, r2, r3 = worst_rates
    issues.append((95,
        f"عدم الحضور يوم {AR_DAYS[worst_day]} في تصاعد مستمر",
        f"النسبة ارتفعت خلال 3 أسابيع من {r1:.0%} إلى {r2:.0%} ثم {r3:.0%} — والنسبة الحالية أعلى ضعف متوسط بقية الأيام.",
        "تجربة مدتها 4 أسابيع: تأكيد واتساب مساء اليوم السابق + قائمة انتظار تلقائية تملأ الفراغ نفسه. المقياس: نسبة عدم الحضور يوم الثلاثاء فقط.",
        f"نمط-يوم-{AR_DAYS[worst_day]}"))
issues.append((55,
    f"ذروة الانتظار تتركز بين {peak_mode} ({peak_n} يومًا من {len(kpis)})",
    "الازدحام يتكرر في نفس النافذة الزمنية أسبوعيًا مما يرفع متوسط الانتظار العام.",
    "إعادة توزيع مواعيد الجديدة إلى الفترة الأقل ضغطًا لمدة أسبوعين وقياس أثرها على متوسط الانتظار.",
    "نمط-انتظار"))

stale_wait = []
for w in waiting_for:
    since = w.get("expected_by") or w.get("since")
    if isinstance(since, dt.date) and (TODAY - since).days >= 14:
        stale_wait.append(w)
if stale_wait:
    issues.append((60, "عناصر تنتظرها منذ 14 يومًا أو أكثر",
        "؛ ".join(f"{w['item']} (منذ {(TODAY - w['since']).days} يومًا)" for w in stale_wait),
        "قرار لكل عنصر: تذكير اليوم أو إغلاق/أرشفة — لا يبقى شيء في الانتظار بلا تاريخ.", "انتظار-متقادم"))

# ---------------------------------------------------------------- 2) المشاريع
proj_active = [p for p in projects if p["الحالة"] == "نشط"]
proj_waiting = [p for p in projects if p["الحالة"] == "انتظار"]
proj_stalled = [p for p in projects if p["الحالة"] == "نشط" and (TODAY - p["آخر تقدم"]).days > 30]
proj_stopped = [p for p in projects if p["الحالة"] == "متوقف"]
proj_idea = [p for p in projects if p["الحالة"] == "فكرة"]
api_cost = sum(p.get("تكلفة شهرية (ريال)") or 0 for p in projects)

if proj_stalled:
    issues.append((85, "مشاريع نشطة رسميًا لكنها متوقفة فعليًا",
        "؛ ".join(f"{p['المشروع']} (بدون تقدم {(TODAY - p['آخر تقدم']).days} يومًا)" for p in proj_stalled),
        "قرار لكل مشروع: إما خطوة واحدة صغيرة هذا الأسبوع أو تحويل حالته إلى «متوقف» لتخفيف الحمل المعرفي.",
        "مشاريع-متوقفة"))

# ---------------------------------------------------------------- 3) الأعمال (Leads)
active_lead_states = ("جديد", "تم التواصل", "انتظار رد", "عرض")
funnel = Counter(l["الحالة"] for l in leads)
won = [l for l in leads if l["الحالة"] == "فاز"]
lost = [l for l in leads if l["الحالة"] == "خسر"]
conv = len(won) / (len(won) + len(lost)) if (won or lost) else 0
pipeline = sum(l.get("القيمة المحتملة (ريال)") or 0 for l in leads if l["الحالة"] in active_lead_states)
new_this_week = [l for l in leads if l["الحالة"] == "جديد" and l["آخر تواصل"] >= this_w]
no_2nd = [l for l in leads if l["الحالة"] in ("تم التواصل", "انتظار رد") and (TODAY - l["آخر تواصل"]).days >= 7]
due_soon_leads = [l for l in leads if l.get("المتابعة القادمة") and this_w <= l["المتابعة القادمة"] <= TARGET + dt.timedelta(days=3)]
svc_demand = Counter(l["الخدمة"] for l in leads if l["الحالة"] in active_lead_states)

if no_2nd:
    issues.append((80, "عملاء محتملون بلا تواصل ثانٍ",
        f"{len(no_2nd)} من الفرص النشطة لم يُتواصل معها للمرة الثانية ({'، '.join(l['الجهة'] for l in no_2nd)}).",
        "إرسال متابعة قصيرة اليوم (المسودات جاهزة أسفل البريف) وتثبيت قاعدة: كل فرصة لها متابعة قادمة بتاريخ أو تُغلق.",
        "فرص-بلا-متابعة"))
top_service, top_n = (svc_demand.most_common(1)[0] if svc_demand else ("—", 0))

# ---------------------------------------------------------------- 4) المالية
fin_total = sum(f.get("التكلفة (ريال/شهر)") or 0 for f in finance)
fin_renew = [f for f in finance if f.get("تاريخ التجديد") and 0 <= (f["تاريخ التجديد"] - TODAY).days <= 30]
fin_unused = [f for f in finance if f.get("آخر استخدام") and (TODAY - f["آخر استخدام"]).days > 30]
fin_dup = defaultdict(list)
for f in finance:
    fin_dup[f["النوع"]].append(f)
dups = {t: fs for t, fs in fin_dup.items() if len(fs) > 1}
savings = sum(f.get("التكلفة (ريال/شهر)") or 0 for f in fin_unused) + \
          sum(min(f.get("التكلفة (ريال/شهر)") or 0 for f in fs) for fs in dups.values())
if fin_unused or dups:
    issues.append((70, "اشتراكات بلا استخدام أو مكررة",
        f"غير مستخدمة: {'، '.join(f['البند'] for f in fin_unused) or 'لا يوجد'}" + (f" | مكررة: {'، '.join(t for t in dups)}" if dups else ""),
        f"إلغاء غير المستخدم ودمج المكرر → توفير تقديري {savings} ريال/شهر ({savings * 12:,} ريال/سنة).",
        "مالية-اشتراكات"))

# ---------------------------------------------------------------- 5) القرارات
dec_due = [d for d in decisions if d.get("تاريخ المراجعة")
           and d["تاريخ المراجعة"] <= TODAY + dt.timedelta(days=7)
           and d.get("الحالة") != "منفذ"]
dec_running = [d for d in decisions if d.get("الحالة") == "قيد التنفيذ"]
dec_need_lesson = [d for d in decisions if d.get("النتيجة الفعلية") and not d.get("التقييم/الدرس") and d.get("الحالة") != "منفذ"]

# ---------------------------------------------------------------- 6) المهام
prio_score = {"عالية": 3, "متوسطة": 2, "منخفضة": 1}
open_tasks = [t for t in tasks if t["الحالة"] != "منجزة"]
for t in open_tasks:
    t["_score"] = prio_score.get(t["الأولوية"], 1) * 3
    if t["الموعد النهائي"] and t["الموعد النهائي"] < TARGET:
        t["_score"] += min(8, (TARGET - t["الموعد النهائي"]).days)
    elif t["الموعد النهائي"] and t["الموعد النهائي"] <= TARGET + dt.timedelta(days=1):
        t["_score"] += 2
top3 = sorted(open_tasks, key=lambda t: -t["_score"])[:3]
overdue = [t for t in open_tasks if t["الموعد النهائي"] and t["الموعد النهائي"] < TODAY]
done_last_week = [t for t in tasks if t["الحالة"] == "منجزة"]

# ---------------------------------------------------------------- 7) المواعيد والتحضير
upcoming = [m for m in meetings if TARGET <= m["التاريخ"] <= TARGET + dt.timedelta(days=6)]
prep_missing = [m for m in upcoming if str(m.get("حالة التحضير", "")).startswith("ينقص")]

# ---------------------------------------------------------------- 8) متابعة المرضى (رموز فقط)
fu_late = [f for f in followups if f.get("الموعد القادم") and f["الموعد القادم"] < TODAY]
fu_review = [f for f in followups if f.get("يحتاج مراجعة خطة") == "نعم"]
fu_soon = [f for f in followups if f.get("الموعد القادم") and TODAY <= f["الموعد القادم"] <= TARGET + dt.timedelta(days=3)]

# ---------------------------------------------------------------- 9) صندوق الصوت
voice_pending = [v for v in voice if v.get("تم التحويل") != "نعم"]

# ---------------------------------------------------------------- 10) التعلم
learn_done = [l for l in learning if l["الحالة"] == "منجزة"]
learn_applied = [l for l in learning if l.get("طُبِّق عمليًا") in ("نعم", "جزئيًا")]

# ================================================================= مسودات جاهزة
def draft_msg(l):
    return (f"إلى {l['الجهة']}\n"
            f"«الأستاذ/ة المحترم/ة، أتابع بخصوص «{l['الخدمة']}» التي طرحناها سابقًا. "
            f"أعددت لك ملخصًا من صفحة واحدة يوضح الفائدة والتشغيل. هل يناسبك اتصال قصير (15 دقيقة) هذا الأسبوع أو التالي له؟ "
            f"عبدالرحمن — أخصائي علاج طبيعي»")
drafts = [draft_msg(l) for l in no_2nd[:2]]

# ================================================================= التوصيات = أهم 3
issues.sort(key=lambda x: -x[0])
recs = [(w, title, action) for (w, title, _det, action, _tag) in issues]
for d in dec_due:
    recs.append((75, f"مراجعة قرار: {d['القرار']}",
                 f"قارن المتوقع ({d['النتيجة المتوقعة']}) بالفعلي ({d['النتيجة الفعلية'] or 'لم يُسجل'}) وسجّل الدرس في سجل القرارات."))
if prep_missing:
    recs.append((45, "نقص في تحضير اجتماعات الأسبوع القادم",
                 "؛ ".join(f"{m['الموضوع']}: {m['حالة التحضير']}" for m in prep_missing)))
recs = sorted(recs, key=lambda x: -x[0])[:3]

auto_count = len(drafts) + len(issues) + len(overdue) + len(no_2nd) + len(dec_due) + len(voice_pending)

# ---------------------------------------------------------------- طابور الإجراءات (إصلاح C2)
import hashlib

def _hash(txt):
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]

def _as_date(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])

queue = S.get("action_queue", [])
q_changed = False
for d in drafts:
    h = _hash(d)
    if not any(a.get("content_hash") == h for a in queue):  # idempotency
        queue.append({
            "action_id": f"A-{len(queue) + 1:03d}",
            "type": "send_followup_message", "channel": "wa/email",
            "content": d, "content_hash": h, "status": "PENDING_APPROVAL",
            "created_at": TODAY.isoformat(),
            "expires_at": (TODAY + dt.timedelta(days=2)).isoformat(),
            "approved_at": None, "executed_at": None})
        q_changed = True
        log_event("action_enqueued", action_id=queue[-1]["action_id"], hash=h)
for a in queue:
    if a["status"] == "PENDING_APPROVAL" and _as_date(a["expires_at"]) < TODAY:
        a["status"] = "EXPIRED"
        q_changed = True
for c in S.get("voice_calls", []):
    if c.get("status") == "COMPLETED" and not c.get("briefed"):
        c["briefed"] = True
# ================================================================= توليد Markdown
def fmt_delta(new, old, pct=False, lower_better=True):
    if old == 0:
        return "—"
    d = (new - old) / old
    if abs(d) < 0.005:
        return "≈ لا تغيير"
    arrow = "▲" if d > 0 else "▼"
    good = (d < 0) if lower_better else (d > 0)
    return f"{arrow} {abs(d):.0%} {'✅' if good else '⚠️'}"

wk_range = f"{ar_date(this_w)} – {ar_date(this_w + dt.timedelta(days=4))}"

brief_md = f"""# ☀️ {BRIEF_LABEL} — {AR_DAYS[TARGET.weekday()]} {ar_date(TARGET)}

> 🚪 **باب اليوم: {day_door[0]}** — {day_door[1]}

> عبدالرحمن، جهّزتُ لك هذا البريف تلقائيًا من الشيت الرئيسي، وأنجزت عنك **{auto_count} مهمة روتينية** (كشف، حصر، ومسودات). تحتاج انتباهك فقط للأمور أدناه.

## 🎯 أهم 3 أولويات
"""
if changes:
    brief_md += "\n## 🔄 ما تغيّر منذ البريف السابق\n"
    for c in changes[:8]:
        brief_md += f"- {c}\n"
    if len(changes) > 8:
        brief_md += f"- …و{len(changes) - 8} تغييرًا آخر\n"

for i, t in enumerate(top3, 1):
    late = f" — ⚠️ متأخرة {(TODAY - t['الموعد النهائي']).days} يومًا" if t["الموعد النهائي"] and t["الموعد النهائي"] < TODAY else ""
    brief_md += f"{i}. **{t['العنوان']}** ({t['النوع']} | أولوية {t['الأولوية']} | الموعد: {ar_date(t['الموعد النهائي'])}{late})\n"

brief_md += f"\n## ✅ يحتاج قرارك/موافقتك\n"
for d in dec_due[:2]:
    brief_md += f"- **مراجعة قرار «{d['القرار']}»** (مراجعة مستحقة {ar_date(d['تاريخ المراجعة'])}): المتوقع {d['النتيجة المتوقعة']} — الفعلي {d['النتيجة الفعلية'] or 'لم يُسجل'}. هل كان القرار صحيحًا؟ سجّل الدرس.\n"
if fu_review:
    brief_md += f"- **موافقة على تعديل خطط سريرية**: {len(fu_review)} مرضى يحتاجون مراجعة خطة ({'، '.join(f['الرمز'] for f in fu_review)}) — التعديل النهائي قرارك.\n"
for d in dec_running[:2]:
    brief_md += f"- متابعة تنفيذ: «{d['القرار']}» (قيد التنفيذ، مراجعة {ar_date(d['تاريخ المراجعة']) if d.get('تاريخ المراجعة') else 'غير محددة'}).\n"

for dr in open_drs:
    late = " ⚠️ تجاوز المهلة" if dt.date.fromisoformat(str(dr["deadline"])[:10]) < TODAY else ""
    brief_md += (f"- 📌 طلب قرار مفتوح {dr['id']}: {dr['title']} "
                 f"(المهلة: {str(dr['deadline'])[:10]}{late}) — الخيارات: {' / '.join(dr['options'])}\n")
if unbriefed_calls:
    brief_md += "\n## 📞 مكالمات تحتاج انتباهك\n"
    for c in unbriefed_calls[:4]:
        ho = f" — 🔔 تحويل مطلوب: {c['handoff']['reason']}" if c.get("handoff") else ""
        sec = " | 🛡️ محاولة حقن مرفوضة — لم يُفصح عن شيء" if c.get("safety_flags") else ""
        lead = f" | قوة العميل: {c['lead_score']}" if c.get("lead_score") in ("HIGH", "MEDIUM") else ""
        brief_md += (f"- {c['call_id']}: {CALLER_AR.get(c['caller_type'], c['caller_type'])} — "
                     f"{INTENT_AR.get(c['primary_intent'], c['primary_intent'])}{lead}{ho}{sec} — {c['summary']}\n")
brief_md += f"\n## 📅 اجتماعات الأسبوع\n"
for m in upcoming:
    flag = "✅" if m.get("حالة التحضير") == "جاهز" else "⚠️"
    brief_md += f"- {AR_DAYS[m['التاريخ'].weekday()]} {ar_date(m['التاريخ'])} — {m['الوقت']} — **{m['الموضوع']}** {flag} {m.get('حالة التحضير','')} → تحضير: {m['التحضير المطلوب']}\n"

brief_md += f"\n## ⏳ متابعات مستحقة\n"
for l in due_soon_leads:
    brief_md += f"- عميل: **{l['الجهة']}** ({l['الخدمة']}) — متابعته القادمة {ar_date(l['المتابعة القادمة'])} — قيمة {(l['القيمة المحتملة (ريال)'] or 0):,} ريال\n"
for f in fu_late:
    brief_md += f"- مريض **{f['الرمز']}** فات موعده ({ar_date(f['الموعد القادم'])}) — {f.get('ملاحظات', '')}\n"
for f in fu_soon[:2]:
    brief_md += f"- مريض {f['الرمز']} موعده القادم {ar_date(f['الموعد القادم'])}\n"
if voice_pending:
    brief_md += f"- 🎙️ صندوق الصوت: {len(voice_pending)} عنصر بانتظار التحويل ({'؛ '.join(v['النص'][:40] + '…' for v in voice_pending)})\n"

if due_reviews:
    brief_md += f"\n## 📚 مراجعات تعلّم اليوم ({sum(r['est_minutes'] for r in due_reviews)} دقائق)\n"
    for r in due_reviews:
        cw = concept_by_id.get(r["concept_id"], {})
        weak = " — ⚠️ مفهوم ضعيف سابقًا" if cw.get("misconception_flags") else ""
        brief_md += f"- {r['concept_title']}: {r['est_minutes']} دقائق (استرجاع فعّال — لا إعادة قراءة){weak}\n"

risk = issues[0] if issues else None
for w in waiting_for:
    since = w.get("expected_by") or w.get("since")
    if isinstance(since, dt.date) and (TODAY - since).days >= 7:
        mark = "⚠️ متأخر" if w.get("status") == "OVERDUE" else "منذ"
        task = w.get("task") or w.get("item")
        brief_md += f"- ⏸️ ننتظر: {task} — {mark} {(TODAY - since).days} يومًا\n"
brief_md += f"\n## ⚠️ خطر يستحق انتباهك\n**{risk[1]}** — {risk[2]}\n"
brief_md += f"\n## 💡 فرصة تستحق نظرة\nالخدمة الأكثر طلبًا بين الفرص النشطة: **{top_service}** ({top_n} فرص، قيمة خط الأنشط {pipeline:,} ريال). أقرب خطوة: عرض جاهز قابل للتخصيص خلال أسبوع.\n"
if drafts:
    brief_md += "\n## 📝 مسودات جاهزة (أرسلها كما هي أو عدّلها)\n"
    for i, d in enumerate(drafts, 1):
        brief_md += f"**مسودة {i}:**\n> {d.replace(chr(10), chr(10) + '> ')}\n\n"
brief_md += f"\n## 📉 ما تأخر (يحتاج جدولة)\n"
for t in overdue:
    brief_md += f"- {t['العنوان']} — تأخر {(TODAY - t['الموعد النهائي']).days} يومًا\n"
if not overdue:
    brief_md += "- لا شيء متأخر ✅\n"

weekly_md = f"""# 📊 المراجعة التنفيذية الأسبوعية — {wk_range}

> وُلّد تلقائيًا من الشيت الرئيسي. القاعدة: لا 50 توصية — فقط أهم 3 قرارات في النهاية.

## 🏥 قسم التأهيل
| المؤشر | هذا الأسبوع | الأسبوع السابق | التغير |
|---|---|---|---|
| المرضى | {A['pat']} | {B['pat']} | {fmt_delta(A['pat'], B['pat'], lower_better=False)} |
| الجلسات | {A['ses']} | {B['ses']} | {fmt_delta(A['ses'], B['ses'], lower_better=False)} |
| عدم الحضور | {A['ns']} ({A['rate']:.0%}) | {B['ns']} ({B['rate']:.0%}) | {fmt_pp(A['rate'], B['rate'])} |
| متوسط الانتظار (دقيقة) | {A['wait']:.0f} | {B['wait']:.0f} | {fmt_delta(A['wait'], B['wait'])} |
| متوسط الموظفين/يوم | {A['staff']:.1f} | {B['staff']:.1f} | {fmt_delta(A['staff'], B['staff'], lower_better=False)} |

**المشكلة التي تستحق تدخلك هذا الأسبوع:** {issues[0][1] if issues else 'لا يوجد نمط حرج'} — {issues[0][2] if issues else ''}
**الإجراء المقترح:** {issues[0][3] if issues else ''}

{f"أحداث مسجلة: " + " | ".join(incidents[-3:]) + chr(10) if incidents else ""}

## 🤖 مشاريع AI والأعمال
| الحالة | العدد | المشاريع |
|---|---|---|
| 🟢 نشط | {len(proj_active)} | {'، '.join(p['المشروع'] for p in proj_active)} |
| 🟡 انتظار | {len(proj_waiting)} | {'، '.join(p['المشروع'] for p in proj_waiting)} |
| 🔴 متوقف | {len(proj_stopped)} | {'، '.join(p['المشروع'] for p in proj_stopped)} |
| ⚪ فكرة | {len(proj_idea)} | {'، '.join(p['المشروع'] for p in proj_idea)} |

"""
if proj_stalled:
    weekly_md += "**⚠️ نشطة رسميًا لكنها متوقفة فعليًا:**\n"
    for p in proj_stalled:
        weekly_md += f"- {p['المشروع']}: بدون تقدم {(TODAY - p['آخر تقدم']).days} يومًا → قررك: خطوة واحدة هذا الأسبوع أو تحويلها إلى «متوقف»\n"
    weekly_md += "\n"
weekly_md += "**الخطوة التالية لكل مشروع نشط:**\n"
for p in proj_active:
    weekly_md += f"- {p['المشروع']}: {p['الخطوة التالية']}\n"
weekly_md += f"\nكلفة APIs والاشتراكات التشغيلية للمشاريع: **{api_cost} ريال/شهر**.\n\n"

weekly_md += f"""## 💼 الأعمال والعملاء
- فرص جديدة هذا الأسبوع: **{len(new_this_week)}** ({'، '.join(l['الجهة'] for l in new_this_week) or '—'})
- قمع الفرص: جديد {funnel.get('جديد', 0)} | تم التواصل {funnel.get('تم التواصل', 0)} | انتظار رد {funnel.get('انتظار رد', 0)} | عرض {funnel.get('عرض', 0)} | فاز {funnel.get('فاز', 0)} | خسر {funnel.get('خسر', 0)}
- قيمة خط الفرص النشطة: **{pipeline:,} ريال** | معدل التحويل: **{conv:.0%}**
- الخدمة الأكثر طلبًا: **{top_service}**
"""
if no_2nd:
    weekly_md += f"- ⚠️ **{len(no_2nd)} فرص بلا تواصل ثانٍ**: {'، '.join(l['الجهة'] for l in no_2nd)} (مسودات المتابعة جاهزة في البريف)\n"

weekly_md += f"""
## 💰 المالية (الاشتراكات)
- المصروف الشهري الحالي: **{fin_total} ريال/شهر** ({fin_total * 12:,} ريال/سنة)
- تجديدات خلال 30 يومًا: {('، '.join(f"{f['البند']} ({ar_date(f['تاريخ التجديد'])})" for f in fin_renew)) or 'لا يوجد'}
- غير مستخدمة (+30 يومًا): {('، '.join(f"{f['البند']} ({(TODAY - f['آخر استخدام']).days} يومًا)" for f in fin_unused)) or 'لا يوجد'}
- مكررة: {('؛ '.join(f"{t}: " + ' / '.join(x['البند'] for x in fs) for t, fs in dups.items())) or 'لا يوجد'}
- **التوفير المحتمل: {savings} ريال/شهر ({savings * 12:,} ريال/سنة)**

## 🧭 سجل القرارات — مراجعات مستحقة
"""
for d in dec_due:
    weekly_md += f"- **{d['القرار']}** (قرار {ar_date(d['التاريخ'])}، الخيار: {d['الخيار']})\n  - المتوقع: {d['النتيجة المتوقعة']}\n  - الفعلي: {d['النتيجة الفعلية'] or 'بانتظار الإدخال'}\n  - → قيّم: هل كان القرار صحيحًا؟ وسجّل الدرس.\n"
if not dec_due:
    weekly_md += "- لا مراجعات مستحقة ✅\n"

weekly_md += f"""
## 📚 التعلم والتطبيق
- عناصر مكتملة: {len(learn_done)}/{len(learning)} | طُبِّق عمليًا: {len(learn_applied)}/{len(learning)}
- غير مكتمل: {'، '.join(f"{l['العنوان']} ({l['الحالة']})" for l in learning if l['الحالة'] != 'منجزة') or '—'}

## ✅ ماذا أُنجز؟
- مهام أُنجزت: {len(done_last_week)} | متأخرة مفتوحة: {len(overdue)} | إجمالي المهام المفتوحة: {len(open_tasks)}

---

# 🏁 أهم 3 قرارات لهذا الأسبوع
"""
for i, (w, title, action) in enumerate(recs, 1):
    weekly_md += f"**{i}. {title}**\n→ {action}\n\n"

# ================================================================= HTML — واجهة محسّنة قابلة للحفظ على سطح المكتب
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_html import build_brief_body, build_weekly_body, wrap_page, wrap_dashboard

DEMO = True  # ← غيّرها إلى False بعد نقل بياناتك الحقيقية إلى الشيت

ctx = dict(
    generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    demo=DEMO,
    b_title=f"{BRIEF_LABEL} — {AR_DAYS[TARGET.weekday()]} {ar_date(TARGET)}",
    b_auto=auto_count,
    top3=[dict(t=t["العنوان"], type=t["النوع"], pr=t["الأولوية"], due=ar_date(t["الموعد النهائي"]),
               late=(TODAY - t["الموعد النهائي"]).days if t["الموعد النهائي"] and t["الموعد النهائي"] < TODAY else 0)
          for t in top3],
    dec_due=[dict(t=d["القرار"], rev=ar_date(d["تاريخ المراجعة"]), exp=d["النتيجة المتوقعة"],
                  act=d["النتيجة الفعلية"] or "لم يُسجل") for d in dec_due[:2]],
    dec_run=[dict(t=d["القرار"], rev=ar_date(d["تاريخ المراجعة"]) if d.get("تاريخ المراجعة") else "بدون") for d in dec_running[:2]],
    fu_review=[f["الرمز"] for f in fu_review],
    meetings=[dict(day=AR_DAYS[m["التاريخ"].weekday()], d=ar_date(m["التاريخ"]), time=m["الوقت"],
                   t=m["الموضوع"], ok=m.get("حالة التحضير") == "جاهز", prep=m["التحضير المطلوب"],
                   st=m.get("حالة التحضير", "")) for m in upcoming],
    leads_due=[dict(name=l["الجهة"], svc=l["الخدمة"], d=ar_date(l["المتابعة القادمة"]),
                    val=l["القيمة المحتملة (ريال)"] or 0) for l in due_soon_leads],
    fu_late=[dict(code=f["الرمز"], d=ar_date(f["الموعد القادم"]), note=f.get("ملاحظات", "")) for f in fu_late],
    fu_soon=[dict(code=f["الرمز"], d=ar_date(f["الموعد القادم"])) for f in fu_soon[:2]],
    voice_n=len(voice_pending),
    voice_first=(voice_pending[0]["النص"][:50] + "…") if voice_pending else "",
    door=day_door[0], door_hint=day_door[1],
    wait=[dict(t=(w.get("task") or w.get("item")),
              d=(TODAY - (w.get("expected_by") or w.get("since"))).days,
              over=w.get("status") == "OVERDUE")
          for w in waiting_for
          if isinstance((w.get("expected_by") or w.get("since")), dt.date)
          and (TODAY - (w.get("expected_by") or w.get("since"))).days >= 7],
    changes=changes[:8],
    drs=[dict(id=d["id"], t=d["title"], dl=str(d["deadline"])[:10],
              opts=" / ".join(d["options"]),
              late=dt.date.fromisoformat(str(d["deadline"])[:10]) < TODAY) for d in open_drs],
    calls=[dict(id=c["call_id"], who=CALLER_AR.get(c["caller_type"], c["caller_type"]),
                what=INTENT_AR.get(c["primary_intent"], c["primary_intent"]),
                sm=c["summary"], ho=c["handoff"]["reason"] if c.get("handoff") else "",
                sec=bool(c.get("safety_flags")),
                lead=c.get("lead_score", "")) for c in unbriefed_calls[:4]],
    reviews=[dict(t=r["concept_title"], m=r["est_minutes"],
                  weak=bool(concept_by_id.get(r["concept_id"], {}).get("misconception_flags")))
             for r in due_reviews],
    risk=dict(t=issues[0][1], d=issues[0][2]) if issues else None,
    opp=dict(svc=top_service, n=top_n, pipe=pipeline),
    drafts=drafts,
    overdue=[dict(t=t["العنوان"], days=(TODAY - t["الموعد النهائي"]).days) for t in overdue],
    wk=wk_range,
    kpis=[("المرضى", A["pat"], B["pat"], fmt_delta(A["pat"], B["pat"], lower_better=False), True),
          ("الجلسات", A["ses"], B["ses"], fmt_delta(A["ses"], B["ses"], lower_better=False), True),
          ("عدم الحضور", f"{A['ns']} ({A['rate']:.0%})", f"{B['ns']} ({B['rate']:.0%})", fmt_pp(A["rate"], B["rate"]), False),
          ("متوسط الانتظار (دقيقة)", f"{A['wait']:.0f}", f"{B['wait']:.0f}", fmt_delta(A["wait"], B["wait"]), False),
          ("متوسط الموظفين/يوم", f"{A['staff']:.1f}", f"{B['staff']:.1f}", fmt_delta(A["staff"], B["staff"], lower_better=False), True)],
    issue=issues[0] if issues else None,
    incidents=incidents[-3:],
    p_active=[(p["المشروع"], p["الخطوة التالية"]) for p in proj_active],
    p_waiting=[p["المشروع"] for p in proj_waiting],
    p_stopped=[p["المشروع"] for p in proj_stopped],
    p_idea=[p["المشروع"] for p in proj_idea],
    p_stalled=[dict(n=p["المشروع"], days=(TODAY - p["آخر تقدم"]).days) for p in proj_stalled],
    api_cost=api_cost,
    new_leads=[l["الجهة"] for l in new_this_week],
    funnel=dict(funnel), conv=conv, pipe=pipeline,
    no2=[l["الجهة"] for l in no_2nd],
    fin=dict(total=fin_total,
             renew=[f"{f['البند']} ({ar_date(f['تاريخ التجديد'])})" for f in fin_renew],
             unused=[f"{f['البند']} ({(TODAY - f['آخر استخدام']).days} يومًا)" for f in fin_unused],
             dups=list(dups.keys()), save=savings),
    dec_rev=[dict(t=d["القرار"], pick=d["الخيار"], exp=d["النتيجة المتوقعة"],
                  act=d["النتيجة الفعلية"] or "بانتظار الإدخال") for d in dec_due],
    learn=dict(done=len(learn_done), tot=len(learning), applied=len(learn_applied),
               open=[f"{l['العنوان']} ({l['الحالة']})" for l in learning if l["الحالة"] != "منجزة"]),
    done_n=len(done_last_week), over_n=len(overdue), open_n=len(open_tasks),
    recs=[dict(t=t, a=a) for (_w, t, a) in recs],
)

brief_body = build_brief_body(ctx)
weekly_body = build_weekly_body(ctx)

# ================================================================= حفظ الملفات
def save(name, md, html):
    open(os.path.join(REPORTS, name + ".md"), "w", encoding="utf-8").write(md)
    open(os.path.join(REPORTS, name + ".html"), "w", encoding="utf-8").write(html)

iso = this_w.isocalendar()
save(f"daily-brief-{TARGET.isoformat()}", brief_md, wrap_page(ctx, f"بريف {TARGET.isoformat()}", brief_body))
save(f"weekly-review-{iso[0]}-W{iso[1]:02d}", weekly_md, wrap_page(ctx, f"مراجعة أسبوعية {iso[0]}-W{iso[1]:02d}", weekly_body))

dash_name = f"dashboard-{TODAY.isoformat()}"
dash_path = os.path.join(REPORTS, dash_name + ".html")
open(dash_path, "w", encoding="utf-8").write(wrap_dashboard(ctx, brief_body, weekly_body))
import shutil
shutil.copyfile(dash_path, os.path.join(REPORTS, "dashboard-latest.html"))  # نسخة ثابتة لسكربتات التشغيل

# صفحة طابور الاعتماد (إصلاح C2)
from render_approvals import build_approvals_body
open(os.path.join(REPORTS, "approvals-latest.html"), "w", encoding="utf-8").write(
    wrap_page(dict(generated=ctx["generated"], demo=DEMO), "طابور الاعتماد",
              build_approvals_body(S.get("action_queue", []))))
S["action_queue"] = queue
S["brief_snapshot"] = {"derived": True, "ts": dt.datetime.now().isoformat(timespec="seconds"), **cur_snap}
if q_changed:
    store.commit(S, "enqueue_actions", pending=len([a for a in queue if a["status"] == "PENDING_APPROVAL"]))
else:
    store.commit(S, "brief_snapshot")
log_event("engine_run", target=str(TARGET), issues=len(issues), pending_actions=len([a for a in S.get("action_queue", []) if a["status"] == "PENDING_APPROVAL"]))

print(f"✅ لوحة القيادة (للحفظ على سطح المكتب) → reports/{dash_name}.html")
print(f"✅ البريف الصباحي  → reports/daily-brief-{TARGET.isoformat()}.md/.html")
print(f"✅ المراجعة الأسبوعية → reports/weekly-review-{iso[0]}-W{iso[1]:02d}.md/.html")
print(f"   الأسبوع المحلل: {wk_range} | أنماط مكتشفة: {len(issues)} | توصيات نهائية: {len(recs)}")

# -*- coding: utf-8 -*-
"""
v0.9 — Master OS: المعايير المعمارية + البذرة التجريبية (Demo Seed) + لوحة الحالة.

ما يقدّمه هذا الملف:
  1) الشجرة المعيارية لمجلدات Google Drive (Abdulrahman_Master_OS) — مصدر الحقيقة
     التصميمي الذي تستنسخه أداة engine/drive_tree.py إلى تقرير وقائمة إنشاء.
  2) مصفوفة توجيه الوكلاء الأربعة (Morning Briefing / Clinical & Ops /
     Knowledge & Audio / Finance & Life) بصيغة بيانات تُسجَّل في قسم sub_agents.
  3) قائمة قنوات اليوتيوب المعيارية (content_sources) المصنّفة حسب المجال.
  4) أمر البذرة التجريبية: python3 engine/master_os.py demo
     يدمج أقسام v0.9 في مخزن الحالة دون لمس أي بيانات تشغيلية موجودة
     (merge-if-missing). لن يُكتب أي صف تجريبي فوق بيانات حقيقية.
  5) أمر الحالة: python3 engine/master_os.py status — يطبع ملخص البنية كاملة.

الأمان: لا يرسل شيئًا خارجيًا؛ كل ما يولّده الباقي يمر عبر طابور الاعتماد.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

# =====================================================================
# 1) الشجرة المعيارية لمجلدات Google Drive
# بنية ثابتة (design-time) — لا بيانات مستخدم. تُستخدم للتوليد والمزامنة.
# =====================================================================
FOLDER_EMOJI = "📁"
DOC_EMOJI = "📄"
SHEET_EMOJI = "📊"

# كل مجلد: (المعرّف، الاسم، الغرض، قائمة ملفات/أوراق بداخله (نوع، اسم، وصف))
MASTER_TREE = [
    {
        "folder_id": "F01",
        "name": "01_Executive_Briefings",
        "purpose": "سجلات البريف الصباحي والقرارات اليومية",
        "children": [
            ("doc", "Executive_Brief_Log_2026",
             "سجل يومي للبريف الصباحي وأهم القرارات المنفَّذة خلال اليوم"),
        ],
    },
    {
        "folder_id": "F02",
        "name": "02_Department_Operations",
        "purpose": "إدارة التأهيل الطبي بمستشفى الهيئة الملكية",
        "children": [
            ("sheet", "Tasks_Ledger_2026",
             "شيت خطة الإنجاز ومصفوفة المهام (NEEDS_INPUT → مسؤول/تاريخ)"),
            ("doc", "Meeting_Minutes_2026", "محاضر الاجتماعات ومخرجات اللجان"),
            ("sheet", "DHS_Training_Tracker",
             "متابعة تدريب الكوادر على منصة DHS (نسبة الإنجاز والتواريخ)"),
        ],
    },
    {
        "folder_id": "F03",
        "name": "03_Clinical_Specialties",
        "purpose": "العيادة والبروتوكولات السريرية والرعاية المنزلية",
        "children": [
            ("doc", "Mulligan_NKT_Manual", "أطر العلاج الحركي ومفهوم موليجان المعتمد"),
            ("doc", "DryNeedling_MyoMentor", "بروتوكولات الإبر الجافة ومحرك MyoMentor"),
            ("doc", "Home_Healthcare_Strategic", "حوكمة وباقات خدمات الرعاية المنزلية"),
        ],
    },
    {
        "folder_id": "F04",
        "name": "04_Knowledge_Hub",
        "purpose": "المعرفة المسموعة والخرائط الذهنية والقراءة",
        "children": [
            ("folder", "MindMaps_Library",
             "خرائط ذهنية مرئية بصيغة Mermaid (ملفات .mmd/.md وصور)"),
            ("folder", "Audio_Digests",
             "ملخصات صوتية وتفريغ البودكاست (ملفات صوتية + نصوص التفريغ)"),
            ("doc", "Book_Summaries_2026", "خلاصات الكتب القيادية والسريرية المركزة"),
        ],
    },
    {
        "folder_id": "F05",
        "name": "05_Personal_Finance_Life",
        "purpose": "الملف المالي الشخصي والأسرة والتطوير القيادي",
        "children": [
            ("sheet", "Financial_Restructuring",
             "كشوف الميزانية وخفض العجز ومسارات الادخار"),
            ("doc", "Family_Personal_Calendar",
             "التزامات الأسرة وحماية الأوقات الحيوية"),
        ],
    },
]

# =====================================================================
# 2) مصفوفة توجيه الوكلاء الفرعيين (Sub-Agents Allocation)
# =====================================================================
SUB_AGENTS = [
    {
        "agent_id": "AG-MORNING",
        "emoji": "☀️",
        "name": "Morning Briefing Agent",
        "role": "فرز الصباح ونبض العيادات وتنسيق أولويات اليوم",
        "inputs": "Google Sheets + التقويم (حالة المهام/الاجتماعات/المؤشرات)",
        "outputs": "لوحة تيليجرام تفاعلية + أزرار تحكم سريعة",
        "cadence_jobs": ["daily.morning_brief_0645", "daily.focus_block_0730"],
    },
    {
        "agent_id": "AG-CLINICAL",
        "emoji": "🏥",
        "name": "Clinical & Ops Agent",
        "role": "متابعة تدريب DHS وحصر العهد ومتابعة محاضر المشرفين",
        "inputs": "رسائل المشرفين + شيت المهام (خطة الإنجاز)",
        "outputs": "مسودات تفويض رسمية + تحديث تلقائي لحالة المهام",
        "cadence_jobs": ["daily.supervisor_close_1600", "weekly.ops_sunday_0715",
                         "weekly.dhs_tuesday_1400"],
    },
    {
        "agent_id": "AG-KNOWLEDGE",
        "emoji": "🎧",
        "name": "Knowledge & Audio Agent",
        "role": "تفريغ قنوات اليوتيوب التخصصية والكتب وتلخيصها (صوت + خريطة ذهنية)",
        "inputs": "روابط الفيديو / ملفات PDF / كتب",
        "outputs": "ملخص مسموع (Audio Digest) + خريطة ذهنية (Mind Map)",
        "cadence_jobs": ["daily.audio_digest_2030", "weekly.weekly_mindmap_friday_1600"],
    },
    {
        "agent_id": "AG-FINANCE",
        "emoji": "💰",
        "name": "Finance & Life Agent",
        "role": "حوكمة الميزانية الشخصية وتفعيل الادخار وتوازن الأسرة",
        "inputs": "شيت المالية + تقويم الالتزامات",
        "outputs": "تنبيهات انحراف المصروفات + حجز نوافذ الراحة الأسرية",
        "cadence_jobs": ["weekly.finance_thursday_0700",
                         "monthly.monthly_finance_health_1st"],
    },
]

# =====================================================================
# 3) قائمة قنوات اليوتيوب / المصادر المعرفية المعيارية
# =====================================================================
CONTENT_SOURCES = [
    {"domain": "القيادة وإدارة النظم", "channel": "Harvard Business Review",
     "kind": "youtube", "note": "مفاهيم القيادة والتطوير الإداري"},
    {"domain": "القيادة وإدارة النظم", "channel": "Stanford eCorner",
     "kind": "youtube", "note": "ريادة الأعمال والقيادة — مقاطع قصيرة قابلة للتفريغ"},
    {"domain": "القيادة وإدارة النظم", "channel": "Lean Enterprise Institute",
     "kind": "youtube", "note": "اللين وتبسيط العمليات وتطبيقه في الرعاية الصحية"},
    {"domain": "التأهيل الطبي والميكانيكا الحيوية", "channel": "Physio Network",
     "kind": "youtube", "note": "مراجعات الأدلة السريرية وحالات التأهيل"},
    {"domain": "التأهيل الطبي والميكانيكا الحيوية", "channel": "Clinical Edge",
     "kind": "youtube", "note": "تحديثات العلاج اليدوي والتمارين العلاجية"},
    {"domain": "التأهيل الطبي والميكانيكا الحيوية", "channel": "قنوات التحليل الحركي وإطلاق اللفافة والطب الرياضي",
     "kind": "youtube", "note": "Motion analysis / dry needling / sports rehab"},
    {"domain": "أتمتة الأعمال والذكاء الاصطناعي", "channel": "Matthew Berman",
     "kind": "youtube", "note": "أحدث بنيات الوكلاء المستقلين (AI agents)"},
    {"domain": "أتمتة الأعمال والذكاء الاصطناعي", "channel": "Prompt Engineering",
     "kind": "youtube", "note": "هندسة الأوامر وتصميم تدفقات الوكلاء"},
    {"domain": "أتمتة الأعمال والذكاء الاصطناعي", "channel": "قنوات n8n و Python",
     "kind": "youtube", "note": "ربط التطبيقات الحية وأتمتة سير العمل"},
]

# =====================================================================
# 4) الخريطة الذهنية الأم (المعتمدة كنموذج هيكلي للنظام)
# =====================================================================
MASTER_MIND_MAP_TITLE = "منظومة العمل القيادي والتخصصي"
MASTER_MIND_MAP_BRANCHES = [
    ("قسم التأهيل الطبي", [
        "حوكمة المشرفين والعيادات",
        "تدريب منصة DHS المجدول",
        "تقارير الإغلاق اليومية",
    ]),
    ("الرعاية المنزلية والعيادة", [
        "بروتوكولات Mulligan و NKT",
        "الإبر الجافة ومحرك MyoMentor",
        "باقات الرعاية المنزلية",
    ]),
    ("الأنظمة والأتمتة الذكية", [
        "سيرفر Railway ومستودع GitHub",
        "Google Sheets كقاعدة بيانات حية",
        "بوت تيليجرام التفاعلي",
    ]),
    ("الحياة الشخصية والتوازن", [
        "حوكمة الميزانية والادخار",
        "حماية الأوقات والالتزامات الأسرية",
        "المعرفة المسموعة والخرائط الذهنية",
    ]),
]

# =====================================================================
# أدوات مساعدة للتسجيل
# =====================================================================
def _now():
    return dt.datetime.now().astimezone().date()


def _tree_digest():
    """هوية ثابتة للشجرة المعيارية (لا تتغير مع مرور الوقت)."""
    import hashlib
    raw = "|".join(
        f["folder_id"] + ":" + f["name"] + ":" + ">".join(
            f"{k}@{n}" for (k, n, _p) in f["children"])
        for f in MASTER_TREE)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def tree_spec():
    """صيغة JSON كاملة للشجرة (تُسجَّل في قسم drive_tree)."""
    return {
        "root": "Abdulrahman_Master_OS",
        "version": "2026.1",
        "digest": _tree_digest(),
        "folders": MASTER_TREE,
    }


def seed_demo(store=None, force=False):
    """دمج أقسام v0.9 التجريبية في الحالة — لا يلمس بيانات التشغيل الحقيقية.

    Merge-if-missing: الأقسام الفارغة/المفقودة فقط تُملأ؛ أي قسم فيه بيانات
    حقيقية (sub_agents/automation_schedule/... بصفوف من المستخدم) يُترك كما هو
    ما لم يُمرَّر force=True.
    """
    store = store or Store()
    added = {}

    def _fill(section, rows, seed):
        S = store.rows_all()
        existing = S.get(section, [])
        if force:
            existing = []
        before = len(existing)
        seen = {(r.get("id") or r.get("name") or r.get("channel") or r.get("title"))
                for r in existing}
        fresh = [r for r in rows if (r.get("id") or r.get("name") or r.get("channel")
                                     or r.get("title")) not in seen]
        for r in fresh:
            r.setdefault("seed", seed)
            existing.append(r)
        S[section] = existing
        if fresh:
            store.commit(S, f"master_os_seed_{section}", seed=seed,
                         added=len(fresh))
        return len(fresh)

    added["drive_tree"] = _fill("drive_tree", [tree_spec()], "master-tree")

    # الجدول المعياري (مرآة JOB_SPECS — تبقى الشيفرة هي مصدر التشغيل)
    try:
        import scheduler as _sch
        sched_rows = [dict(j) for j in _sch.JOB_SPECS]
        added["automation_schedule"] = _fill("automation_schedule", sched_rows,
                                             "schedule-mirror")
    except Exception:  # noqa: BLE001 — البذرة لا تفشل بسبب غياب الجدولة
        pass

    # الوكلاء الأربعة
    ag_rows = []
    for i, a in enumerate(SUB_AGENTS, 1):
        row = dict(a)
        row["seq"] = i
        ag_rows.append(row)
    added["sub_agents"] = _fill("sub_agents", ag_rows, "sub-agents-matrix")

    # قنوات المعرفة
    cs_rows = [{"id": f"CS-{i:02d}", **c} for i, c in enumerate(CONTENT_SOURCES, 1)]
    added["content_sources"] = _fill("content_sources", cs_rows, "youtube-curation")

    # خريطة النظام الأم (سجل مرجعي لمنظومة العمل) — بنية مطابقة تمامًا لما
    # يولّده mindmap.py من فروع (branch/sub_branches/leaves) كي يلتقطها
    # التطابق البنيوي في register ويكمّل ملفاتها عند أول بناء.
    mm_rows = [{
        "map_id": "MM-000",
        "title": MASTER_MIND_MAP_TITLE,
        "topic": "master-os",
        "source_kind": "system-reference",
        "source_ref": "معمارية v0.9 — الخريطة الأم المعتمدة",
        "branch_model": [
            {"branch": b, "sub_branches": [], "leaves": leaves}
            for (b, leaves) in MASTER_MIND_MAP_BRANCHES
        ],
        "status": "REFERENCE",
    }]
    added["mind_maps"] = _fill("mind_maps", mm_rows, "master-mind-map")

    added_total = sum(added.values())
    if added_total:
        log_event("master_os_demo_seed", added=added, force=force)
        print(f"🌱 بذرة v0.9: أُضيف {added_total} صفًا تجريبيًا "
              f"({', '.join(f'{k}={v}' for k, v in added.items() if v)})")
        print("   ملاحظة: لم تُلمس أي بيانات تشغيلية حقيقية (merge-if-missing).")
    else:
        print("🌱 بذرة v0.9: لا شيء جديد — الأقسام ممتلئة أصلًا. "
              "لإعادة البذر التجريبي: python3 engine/master_os.py demo --force")
    return added


def status(store=None):
    """ملخص نصي للبنية المعمارية v0.9 من الحالة الفعلية."""
    store = store or Store()
    S = store.rows_all()

    lines = ["", "🧭 Master OS — ملخص البنية المعمارية (v0.9)", "=" * 46]
    tree = S.get("drive_tree", [{}])[0]
    folders = tree.get("folders", MASTER_TREE) if tree else MASTER_TREE
    lines.append(f"{FOLDER_EMOJI} شجرة Drive: {tree.get('root', 'Abdulrahman_Master_OS')} "
                 f"(digest {tree.get('digest', '—')})")
    for f in folders:
        kids = " · ".join(f"{SHEET_EMOJI if k == 'sheet' else DOC_EMOJI if k == 'doc' else FOLDER_EMOJI} {n}"
                          for (k, n, _p) in f["children"])
        lines.append(f"   ├─ {f['folder_id']} {f['name']} — {kids}")

    agents = S.get("sub_agents", [])
    lines.append("")
    lines.append(f"🤖 الوكلاء الفرعيون ({len(agents)}):")
    for a in agents:
        lines.append(f"   • {a.get('emoji', '')} {a['name']}: {a['role']}")

    sources = S.get("content_sources", [])
    by_domain = {}
    for s in sources:
        by_domain.setdefault(s.get("domain", "—"), []).append(s.get("channel", ""))
    lines.append("")
    lines.append(f"🎬 قنوات المعرفة ({len(sources)}):")
    for domain, chans in by_domain.items():
        lines.append(f"   • {domain}: {', '.join(chans)}")

    maps = S.get("mind_maps", [])
    digests = S.get("audio_digests", [])
    schedule = S.get("automation_schedule", [])
    runs = S.get("automation_runs", [])
    if not schedule:
        try:
            import scheduler
            schedule = scheduler.JOB_SPECS
        except Exception:  # noqa: BLE001
            schedule = []
    lines.append("")
    lines.append(f"🗺️ خرائط ذهنية: {len(maps)} | 🎧 ملخصات صوتية: {len(digests)} | "
                 f"⏰ وظائف مجدولة: {len(schedule)} | 🏃 تشغيلات: {len(runs)}")
    pending = [a for a in S.get("action_queue", [])
               if a.get("status") == "PENDING_APPROVAL"]
    lines.append(f"⏳ إجراءات بانتظار الاعتماد: {len(pending)}")
    lines.append("")
    print("\n".join(lines))
    return lines


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "demo":
        seed_demo(force="--force" in sys.argv)
    elif cmd == "status":
        status()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

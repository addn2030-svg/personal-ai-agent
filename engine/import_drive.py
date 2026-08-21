# -*- coding: utf-8 -*-
"""
جسر Google Drive — يربط ملفاتك الحقيقية بنظامك.

  python3 engine/import_drive.py --sheet   # يستورد «خطة الإنجاز والمهام» مباشرة من Google Sheets (حي)
  python3 engine/import_drive.py --plan    # يستورد خطة أسبوع «سرعة الحسم» (20–26 أغسطس) + قراراتها الموثقة

قواعد:
  - Idempotent: الصفوف المستوردة سابقًا (نفس العنوان + المصدر) لا تتكرر.
  - الشيت يُقرأ لأنه «أي شخص لديه الرابط يطّلع» — لو قيدت الوصول لاحقًا، صدّره يدويًا وعدّل SHEET_CSV.
"""
import csv
import datetime as dt
import io
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()
SHEET_CSV = "https://docs.google.com/spreadsheets/d/1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc/gviz/tq?tqx=out:csv"
SOURCE_SHEET = "Google Sheet"

PRIO = {"عالي": "عالية", "متوسط": "متوسطة", "منخفض": "منخفضة"}


def _task_type(title, classification):
    t = title.lower()
    if any(k in title for k in ("AI", "الذكاء الاصطناعي", "برمجة", "وكيل", "برنامج")):
        return "AI"
    if "lean" in t:
        return "تعلم"
    if "mxbd" in t or "هيرمان" in title or "قيادة" in title:
        return "تعلم"
    return "شخصي" if classification == "شخصي" else "أعمال"


def import_sheet():
    print("⏳ قراءة الشيت مباشرة من Google Sheets...")
    data = urllib.request.urlopen(SHEET_CSV, timeout=25).read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(data)))
    hdr_i = next(i for i, r in enumerate(rows) if "المهام" in r)
    hdr = rows[hdr_i]
    ix = {h: hdr.index(h) for h in hdr if h}

    store = Store()
    S = store.rows_all()
    existing = {(t.get("العنوان"), t.get("المصدر")) for t in S["tasks"]}
    added, skipped = 0, 0
    for r in rows[hdr_i + 1:]:
        g = lambda k: (r[ix[k]].strip() if k in ix and ix[k] < len(r) else "")
        title = g("المهام")
        if not title:
            continue
        classification = g("التصنيف")
        importance = g("الأهمية")
        if not classification and not importance:
            skipped += 1  # مبدأ/ملاحظة بلا تصنيف — ليست مهمة قابلة للجدولة
            continue
        if (title, SOURCE_SHEET) in existing:
            skipped += 1
            continue
        notes = []
        if g("مستوى التركيز"):
            notes.append(f"مستوى التركيز: {g('مستوى التركيز')}")
        if g("الإلحاح"):
            notes.append(f"الإلحاح: {g('الإلحاح')}")
        if g("الملاحظات"):
            notes.append(g("الملاحظات"))
        if g("الجوانب"):
            notes.append(f"الجانب: {g('الجوانب')}")
        S["tasks"].append({
            "العنوان": title, "النوع": _task_type(title, classification),
            "الأولوية": PRIO.get(importance, "متوسطة"),
            "الموعد النهائي": None, "الحالة": "لم تبدأ",
            "السياق/المشروع": g("الجوانب") or "خطة الإنجاز",
            "المصدر": SOURCE_SHEET, "ملاحظات": " | ".join(notes)})
        added += 1
    if added:
        store.commit(S, "google_sheet_import", tasks=added, skipped=skipped)
        log_event("GOOGLE_SHEET_IMPORTED", tasks=added)
    print(f"✅ الشيت: أُضيفت {added} مهمة حقيقية ({skipped} صفًا تخطي: مكرر أو غير مجدول)")
    if added:
        print("   منها عالية الأهمية:", sum(1 for t in S["tasks"][-added:] if t["الأولوية"] == "عالية"))


# ── خطة أسبوع سرعة الحسم (من ملف Google Docs — 20–26 أغسطس 2026) ──
PLAN_DAYS = [
    (dt.date(2026, 8, 20), "اليوم 1: جرد القرارات المعلقة واختيار قرار الأسبوع (متوسط الأثر وقابل للعكس)"),
    (dt.date(2026, 8, 21), "اليوم 2: صياغة خيارين (أ/ب) + 3 معايير تقييم + وزن الثقة %"),
    (dt.date(2026, 8, 22), "اليوم 3: تحليل ما قبل الوفاة (Premortem) + ضبط مؤقت 24 ساعة"),
    (dt.date(2026, 8, 23), "اليوم 4 — يوم الحسم: إعلان القرار المكتوب + الخطوة المادية الأولى خلال 48 ساعة"),
    (dt.date(2026, 8, 24), "اليوم 5: ربط القرار بـOKR مصغر + قائمة Stop-Doing"),
    (dt.date(2026, 8, 25), "اليوم 6: تدريب سرعة الحسم — 3 قرارات صغيرة (خياران + معيار + 10 دقائق)"),
    (dt.date(2026, 8, 26), "اليوم 7: مراجعة جودة العملية + تحديث بطاقة الأداء + تعبئة Google Sheet"),
]
DOC_DECISIONS = [
    ("الوصول لوزن < 90 كغ خلال شهرين", "(B) تمارين + عجز سعرات", "الاستدامة، الطاقة، سهولة القياس", "70%"),
    ("تعزيز حب الذات والثقة في الحدس والقدرات", "حديث ذاتي إيجابي + تدوين لحظات الثقة", "الهدوء النفسي، وضوح القرارات", "80%"),
    ("تعزيز التدفق المالي (طلب المقابل بثقة)", "عرض الخدمات بوضوح وطلب المقابل المادي", "الوضوح المالي، الاستدامة، الاستحقاق", "85%"),
]


def import_plan():
    store = Store()
    S = store.rows_all()
    existing = {(t.get("العنوان"), t.get("المصدر")) for t in S["tasks"]}
    added_t = added_d = 0

    for due, title in PLAN_DAYS:
        if (title, "خطة سرعة الحسم") in existing:
            continue
        S["tasks"].append({"العنوان": title, "النوع": "تعلم", "الأولوية": "عالية",
                           "الموعد النهائي": due, "الحالة": "لم تبدأ",
                           "السياق/المشروع": "بروتوكول سرعة الحسم V2",
                           "المصدر": "خطة سرعة الحسم", "ملاحظات": ""})
        added_t += 1

    for name, choice, criteria, conf in DOC_DECISIONS:
        if any(d.get("القرار") == name for d in S["decisions"]):
            continue
        S["decisions"].append({"التاريخ": dt.date(2026, 8, 20), "القرار": name,
                               "البدائل المدروسة": criteria, "الخيار": choice,
                               "النتيجة المتوقعة": f"وفق معايير: {criteria} (ثقة {conf})",
                               "تاريخ المراجعة": dt.date(2026, 9, 21), "النتيجة الفعلية": None,
                               "الحالة": "قيد التنفيذ", "التقييم/الدرس": f"سجل موثق من Google Docs — ثقة {conf}"})
        added_d += 1

    # قرار الأسبوع ← طلب قرار رسمي يوم الحسم السبت 23 أغسطس
    if not any(d.get("id") == "DR-002" for d in S.get("decision_requests", [])):
        S["decision_requests"].append({
            "id": "DR-002", "project": None,
            "title": "قرار الأسبوع (سرعة الحسم): المشروع التجريبي الأول — Life Pulse أم MyoMentor؟",
            "context": "قرار قابل للعكس + أثر عالٍ ← البروتوكول: 24–72 ساعة بثقة 60–70%، خياران فقط، 3 معايير",
            "options": ["أ — Life Pulse (له زخم وبيانات مرضى اختبار)", "ب — MyoMentor (فكرة أبكر بلا التزامات)"],
            "deadline": dt.date(2026, 8, 23).isoformat(), "status": "PENDING",
            "created_at": TODAY.isoformat(), "resolved_at": None, "resolution": None})
        print("🧭 أُنشئ DR-002: قرار الأسبوع (يوم الحسم السبت 23 أغسطس) — سيطاردك اللوحة حتى تُحسم")

    if not any(p.get("المشروع") == "MyoMentor" for p in S["projects"]):
        S["projects"].append({"المشروع": "MyoMentor", "المجال": "AI", "الحالة": "فكرة",
                              "آخر تقدم": TODAY, "الخطوة التالية": "يُقيَّم مقابل Life Pulse في DR-002 (يوم الحسم)",
                              "الأولوية": "عالية", "تكلفة شهرية (ريال)": 0, "ملاحظات": "من شيت Google + خطة سرعة الحسم"})

    store.commit(S, "gdoc_plan_import", tasks=added_t, decisions=added_d)
    log_event("GDOC_PLAN_IMPORTED", tasks=added_t, decisions=added_d)
    print(f"✅ خطة الأسبوع: {added_t} مهام بتواريخ 20–26 أغسطس + {added_d} قرارات موثقة (ثقة 70–85%)")




def import_sources(url):
    """يستورد شيت «المصادر والتعلم العلمي»: المصدر | النوع والموضوع | الفكرة الرئيسية | التطبيق خلال 24 ساعة."""
    csv_url = url.strip().replace("/edit", "").replace("?usp=drivesdk", "") + "/gviz/tq?tqx=out:csv"
    print("⏳ قراءة شيت المصادر من Google Sheets...")
    data = urllib.request.urlopen(csv_url, timeout=25).read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(data)))
    hdr_i = 0
    for i, r in enumerate(rows[:5]):
        if any("المصدر" in c for c in r):
            hdr_i = i
            break
    hdr = rows[hdr_i]
    ix = {h: hdr.index(h) for h in hdr if h}
    store = Store()
    S = store.rows_all()
    existing = {k.get("source") for k in S.get("knowledge_sources", [])}
    added = 0
    for r in rows[hdr_i + 1:]:
        g = lambda k: (r[ix[k]].strip() if k in ix and ix[k] < len(r) else "")
        src = g("المصدر")
        if not src or src in existing:
            continue
        S["knowledge_sources"].append({
            "source": src, "type_topic": g("النوع والموضوع"),
            "key_idea": g("الفكرة الرئيسية"),
            "apply_24h": g("التطبيق خلال 24 ساعة"),
            "linked_concept": None,
            "added_at": TODAY.isoformat(), "status": "جديد"})
        added += 1
    if added:
        store.commit(S, "knowledge_sources_import", sources=added)
        log_event("KNOWLEDGE_SOURCES_IMPORTED", sources=added)
    print(f"✅ أُضيف {added} مصدرًا علميًا — كل مصدر يحمل تطبيق 24 ساعة حتى يُطبَّق")


if __name__ == "__main__":
    if "--sheet" in sys.argv:
        import_sheet()
    elif "--plan" in sys.argv:
        import_plan()
    elif "--sources" in sys.argv and len(sys.argv) > 2:
        import_sources(sys.argv[2])
    else:
        print(__doc__)

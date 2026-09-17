#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌱 إدخال التوصيات التشغيلية في Google Sheets
Writes curated operational recommendations across all key tabs.

التشغيل على Railway / الإنتاج:
  python3 scripts/seed_recommendations.py              ← عرض معاينة فقط (dry-run)
  python3 scripts/seed_recommendations.py --apply       ← إدخال فعلي في الشيت
  python3 scripts/seed_recommendations.py --apply --idempotent ← تخطي التبويبات المُدخلة مسبقًا

المتطلبات:
  - GOOGLE_SHEET_ID
  - GOOGLE_SERVICE_ACCOUNT_JSON

الأمان:
  ✅ لا يحذف أي بيانات موجودة أبدًا (append فقط)
  ✅ يضيف التوصيات تحت البيانات الحالية
  ✅ يتحقق من وجود التبويب قبل الكتابة
  ✅ --idempotent: يحفظ بصمة الإدخال ولا يُعيد
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "connectors"))

# ──────────────────────────────────────────────────────────────────────────────
# محتوى التوصيات — كل تبويب بقائمة صفوف [[col1, col2, ...], ...]
# ──────────────────────────────────────────────────────────────────────────────

RECOMMENDATIONS = {}

# ── 1) التطوير الشخصي ─────────────────────────────────────────────────────
RECOMMENDATIONS["التطوير_PERSONAL_شخصي"] = [
    ["الهدف", "المجال", "الأولوية", "الحالة الحالية", "المقياس", "الخطوة التالية", "الموعد"],
    # ── مهارات القيادة ──
    ["إتقان تفويض المهام بفعالية", "القيادة", "عالية", "تفويض جزئي — يحتاج تعميق",
     "عدد المهام المفوضة أسبوعيًا ≥ 5", "تحديد مهمتين جديدتين للتفويض هذا الأسبوع", "2026-10-01"],
    ["بناء فريق مستقل يعمل بدون إشراف مباشر", "القيادة", "عالية", "مرحلة التأسيس",
     "الفريق ينجز 80% بدون تدخل يومي", "توثيق الإجراءات القياسية SOP لقسمين", "2026-10-15"],
    ["تحسين مهارات العرض والتقديم", "التواصل", "متوسطة", "يحتاج تطبيق",
     "عرض واحد مسجل شهريًا مع مراجعة ذاتية", "تسجيل عرض تجريبي 5 دقائق الأسبوع القادم", "2026-10-01"],
    # ── العادات الإنتاجية ──
    ["تثبيت عادة القراءة اليومية 30 دقيقة", "العادات", "عالية", "غير منتظمة",
     "7 أيام متتالية قراءة فعّالة", "وضع مهلة يومية 20:30 في التقويم", "2026-09-22"],
    ["تقليل مقاطعات الرسائل خلال نوافذ التركيز", "الإنتاجية", "عالية", "نافذة واحدة يوميًا",
     "نوافذ تركيز 90 دقيقة بلا مقاطعة ≥ 4/أسبوع", "تفعيل Do Not Disturb 09:00–10:30 يوميًا", "2026-09-20"],
    ["مراجعة أسبوعية كل أربعاء مساءً", "العادات", "متوسطة", "غير منتظمة",
     "مراجعة أسبوعية مكتملة ≥ 3/شهر", "إعداد قالب مراجعة أسبوعية ثابت", "2026-09-24"],
    # ── التعلم المهني ──
    ["إتمام دورة Lean Six Sigma للرعاية الصحية", "التعلم", "عالية", "في التقدم (LP-001)",
     "إكمال الوحدة 3 واختبار", "حجز جلسة 60 دقيقة لإنهاء الوحدة 3", "2026-09-30"],
    ["تطبيق بروتوكول العلاج بالوخز الجاف المتقدم", "السريري", "متوسطة", "نظرية مكتملة — يحتاج تطبيق عملي",
     "3 حالات شهرية بتوثيق قبل/بعد", "تحديد مريض مناسب للتطبيق القادم", "2026-10-05"],
    ["إتقان تحليل الحركة باستخدام تقنيات AI", "التقنية", "منخفضة", "بحث ودراسة",
     "مشروع تجريبي واحد يعمل", "جمع 5 فيديوهات تحليل حركة كبيانات تدريب", "2026-11-01"],
    # ── الصحة والتوازن ──
    ["النوم 7+ ساعات 5 أيام أسبوعيًا", "الصحة", "عالية", "متوسط 6 ساعات",
     "متوسط النوم ≥ 7 ساعات عبر الساعة الذكية", "موعد نوم ثابت 22:30 + روتين مسائي", "2026-09-25"],
    ["نشاط بدني 3 مرات أسبوعيًا", "الصحة", "عالية", "مرتان أسبوعيًا",
     "3 جلسات مسجلة أسبوعيًا", "جدولة سباحة الأحد والثلاثاء + مشي الخميس", "2026-09-22"],
]

# ── 2) مكتبة العبارات التوجيهية ──────────────────────────────────────────
RECOMMENDATIONS["مكتبة العبارات التوجيهية"] = [
    ["العبارة", "الفئة", "متى تُستخدم", "التأثير المتوقع", "ملاحظات"],
    # ── هوية وقيم ──
    ["أنا قائد يبني أنظمة تخدم الناس، لا أنظمة تخدمني", "هوية",
     "عند اتخاذ قرار تشغيلي كبير", "يركّز على البعد الخدمي للقيادة"],
    ["أعمل ب excellency لا ب perfect — الإتقان لا يعني التعطيل", "إنتاجية",
     "عند التردد في البدء أو التأجيل", "يمنع شلل الكمال ويدفع للإنجاز"],
    ["أنا مسؤول عن النظام، ونظامي مسؤول عني", "مسؤولية",
     "في المراجعة الأسبوعية", "يعزز العلاقة التبادلية مع النظام"],
    ["صحتي ليست خيارًا — هي البنية التحتية لكل شيء", "صحة",
     "عند التردد في إلغاء تمرين أو تأخير النوم", "يجعل الصحة أولوية غير قابلة للتفاوض"],
    ["أبني مرة وأستفيد للأبد — التكرار عدو الإنتاجية", "أتمتة",
     "عند مواجهة مهمة متكررة", "يدفع للأتمتة وتوثيق الإجراءات"],
    # ── مواجهة التحديات ──
    ["المشكلة الواضحة نصف الحل — وضّح قبل أن تحل", "تحليل",
     "عند مواجهة مشكلة معقدة", "يجبر على الوضوح قبل الإنفاق"],
    ["لا أؤجل القرارات الصعبة — التأخير يُكلّف أكثر", "قرارات",
     "عند تجنب قرار صعب", "يقلل من تكاليف التأجيل"],
    ["كل 'لا' واعية هي 'نعم' لشيء أهم", "أولويات",
     "عند رفض طلب أو فرصة", "تبرير نفسي للرفض الواعي"],
    ["لا أحد ينجح وحده — طلب المساعدة قوة لا ضعف", "تعاون",
     "عند الحمّل الزائد", "يعزز بناء الفريق والتفويض"],
    ["أقيس ما أريد تحسينه — لا قياس لا تحسين", "قياس",
     "عند بدء أي مشروع أو مبادرة", "يضمن وجود معايير موضوعية"],
    # ── تحفيز وإلهام ──
    ["أبدأ بـ 2 دقيقة — الحركة تخلق الحماس لا العكس", "تحفيز",
     "عند المقاومة النفسية للبدء", "يخفّض حاجز البدء"],
    ["أنا لست ملزماً بإنهاء كل شيء اليوم — فقط بالبدء", "توازن",
     "عند الشعور بالضغط", "يمنع الإنهاك ويعزز الاستمرارية"],
    ["الحمد لله على كل حال — الرضا قوة", "روحانية",
     "في moments of挫折 أو خيبة", "يعيد التوازن النفسي"],
]

# ── 3) الهوية الشخصية ────────────────────────────────────────────────────
RECOMMENDATIONS["الهوية الشخصية"] = [
    ["المفتاح", "القيمة"],
    ["الاسم الكامل", "عبدالرحمن بكور حوسوي"],
    ["المهنة الأساسية", "أخصائي علاج طبيعي — مدير قسم التأهيل"],
    ["المؤسسة", "مستشفى الهيئة الملكية بالجبيل"],
    # ── القيم الجوهرية ──
    ["قيمة جوهرية 1", "ال excellency التشغيلي — بناء أنظمة تعمل بغض النظر عن الظروف"],
    ["قيمة جوهرية 2", "خدمة الناس — التأهيل الطبي كمهمة إنسانية قبل أن يكون وظيفة"],
    ["قيمة جوهرية 3", "التعلم المستمر — كل يوم skill جديد أو تعميق معرفي"],
    ["قيمة جوهرية 4", "التوازن — الصحة والأسرة والعمل نظام متكامل لا تنازلات"],
    ["قيمة جوهرية 5", "الاستقلالية — بناء مصادر دخل متعددة تعتمد على القيمة لا على الوقت"],
    # ── الرؤية ──
    ["الرؤية 3 سنوات", "قائد قسم تأهيل معترف به إقليمياً + مشاريع أعمال ناشئة تعمل بشكل مستقل"],
    ["الرؤية 10 سنوات", "مساهم رئيسي في تطوير منظومة التأهيل الطبي في السعودية + مستثمر في ريادة الأعمال الصحية"],
    # ── نقاط القوة ──
    ["نقطة قوة 1", "التحليل والأنظمة — تحويل الفوضى إلى عمليات واضحة"],
    ["نقطة قوة 2", "التقنية — القدرة على بناء أدوات ذكية بسرعة"],
    ["نقطة قوة 3", "القيادة الهادئة — اتخاذ قرارات في ضغط دون حزم"],
    # ── نقاط التطوير ──
    ["نقطة تطوير 1", "التفويض — التخلص من العادة القديمة «أنا أعملها أفضل»"],
    ["نقطة قوة تطوير 2", "التسويق الشخصي — مشاركة الإنجازات بثقة لا ت arrogancia"],
    ["نقطة قوة تطوير 3", "الشبكات المهنية — توسيع دائرة العلاقات خارج المستشفى"],
    # ── العبارات التأسيسية ──
    ["مرساة هوية 1", "أنا لست وظيفتي — أنا النظام الذي أبنيه"],
    ["مرساة هوية 2", "النجاح = الأثر × الاستمرارية — لا حجم ولا سرعة"],
    ["مرساة هوية 3", "أعمل اليوم على ما يُريد الغد — لا أُطفئ حرائق اليوم فقط"],
]

# ── 4) 📥 مراجعة اليوم — Inbox ────────────────────────────────────────────
RECOMMENDATIONS["📥 مراجعة اليوم — Inbox"] = [
    ["العنوان", "النوع", "الأولوية", "الحالة", "المصدر", "الإجراء المطلوب", "ملاحظات"],
    ["مراجعة البريف الصباحي والتأكد من تنفيذ Top 3", "مهام يومية", "عالية",
     "لم يبدأ", "النظام التلقائي", "قراءة البريف عند الوصول + تنفيذ أول مهمة خلال ساعة",
     "ينشّأه النظام آليًا كل صباح"],
    ["تحديث حالة المهام المكتملة اليوم", "مهام يومية", "متوسطة",
     "لم يبدأ", "المتابعة الذاتية", "تسجيل كل مهمة مكتملة في الشيت قبل نهاية الدوام",
     "يمنع تراكم المهام غير المحدثة"],
    ["مراجعة طابور الاعتماد وإقرار/رفض المسودات", "قرارات", "عالية",
     "لم يبدأ", "المحرك الاستباقي", "فتح صفحة الاعتماد + اتخاذ قرار لكل عنصر",
     "لا تبقى مسودات أكثر من 48 ساعة"],
    ["الرد على العناصر المتأخرة في قائمة الانتظار", "اتصالات", "عالية",
     "لم يبدأ", "قائمة waiting_for", "إرسال تذكير أو إغلاق كل عنصر > 7 أيام",
     "قاعدة: لا شيء ينتظر أكثر من 14 يوم"],
    ["تسجيل ملاحظات التعلم اليومي", "تطوير شخصي", "متوسطة",
     "لم يبدأ", "التعلم الذاتي", "كتابة ملاحظة واحدة عن شيء تعلمته اليوم",
     "حتى سطر واحد يكفي — الاستمرارية أهم من الكمية"],
    ["فحص الطاقة والإرهاق مساءً", "صحة", "متوسطة",
     "لم يبدأ", "النظام الذاتي", "تسجيل مستوى الطاقة/الإرهاق في سجل الطاقة",
     "يساعد المحرك على اقتراح نوافذ الراحة"],
    ["إرسال متابعة لفرص العمل المعلقة", "أعمال", "عالية",
     "لم يبدأ", "فرص العمل", "مراجعة opportunities بلا تواصل > 7 أيام وإرسال متابعة",
     "المسودات جاهزة في البريف — اعتماد وإرسال"],
]

# ── 5) Executive_Brief — تحديثات لوحة القيادة ────────────────────────────
EXECUTIVE_BRIEF_METRICS = {
    "آخر تحديث للتوصيات التشغيلية": "2026-09-16 (automated seed)",
    "عدد التوصيات المُدخلة": str(sum(len(v) - 1 for v in RECOMMENDATIONS.values())),
    "التبويبات المغطاة": "التطوير الشخصي، العبارات التوجيهية، الهوية الشخصية، Inbox",
    "ملاحظات التوصيات": "هذه التوصيات مبنية على معايير الأداء وأفضل الممارسات — قابلة للتعديل المستمر",
}

# ──────────────────────────────────────────────────────────────────────────────
# محرك الإدخال
# ──────────────────────────────────────────────────────────────────────────────

def _service():
    from connectors import google_credentials
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _get_tabs(service, sheet_id):
    data = service.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties.title"
    ).execute()
    return {s["properties"]["title"] for s in data.get("sheets", [])}


def _append_rows(service, sheet_id, tab, rows):
    safe_tab = tab.replace("'", "''")
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{safe_tab}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def _fingerprint(rows):
    """Stable hash of the recommendation rows (excludes header)."""
    data = rows[1:]
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _tab_has_header(service, sheet_id, tab):
    """Check if a tab already has a header row."""
    safe_tab = tab.replace("'", "''")
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"'{safe_tab}'!A1:A1",
    ).execute()
    values = result.get("values", [])
    return bool(values and values[0] and values[0][0])


def _tab_data_count(service, sheet_id, tab):
    """Count rows in a tab (including header)."""
    safe_tab = tab.replace("'", "''")
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"'{safe_tab}'!A:A",
    ).execute()
    return len(result.get("values", []))


def _seed_marker_exists(service, sheet_id, marker_tab, fingerprint):
    """Check if this fingerprint was already seeded (idempotency)."""
    safe_tab = marker_tab.replace("'", "''")
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{safe_tab}'!A:A",
        ).execute()
        for row in result.get("values", []):
            if row and row[0] == fingerprint:
                return True
    except Exception:
        pass
    return False


def _save_seed_marker(service, sheet_id, marker_tab, fingerprint, summary):
    """Record the seed fingerprint for idempotency."""
    safe_tab = marker_tab.replace("'", "''")
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{safe_tab}'!A:C",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[fingerprint, summary]]},
    ).execute()


def dry_run():
    """Preview what would be written, without touching the sheet."""
    print("🧪 معاينة التوصيات (وضع آمن — لا يُكتب شيء)")
    print("=" * 60)
    total_rows = 0
    for tab, rows in RECOMMENDATIONS.items():
        data_rows = len(rows) - 1
        total_rows += data_rows
        fp = _fingerprint(rows)
        print(f"\n📋 {tab} — {data_rows} صف  (fingerprint: {fp})")
        print(f"   الأعمدة: {' | '.join(rows[0])}")
        for i, row in enumerate(rows[1:], 1):
            preview = " | ".join(str(c)[:40] for c in row[:3])
            print(f"   {i:2d}. {preview}{'...' if len(row) > 3 else ''}")
    print(f"\n{'─' * 60}")
    print(f"📊 الإجمالي: {total_rows} صف توصيات في {len(RECOMMENDATIONS)} تبويب")
    if EXECUTIVE_BRIEF_METRICS:
        print(f"   + {len(EXECUTIVE_BRIEF_METRICS)} مقياس في Executive_Brief")
    print(f"\nلتنفيذ (append فقط — لا يحذف): python3 scripts/seed_recommendations.py --apply")
    print(f"مع حماية التكرار:  python3 scripts/seed_recommendations.py --apply --idempotent")


def apply(idempotent=False):
    """Append recommendations to the live Google Sheet.

    NEVER clears or overwrites existing data. Always appends new rows below
    existing content. With --idempotent, skips tabs that were already seeded
    (tracked via fingerprint in a _seed_log tab).
    """
    from connectors import google_credentials, sheet_intelligence

    sheet_id = sheet_intelligence.SHEET_ID
    if not sheet_id:
        print("❌ GOOGLE_SHEET_ID not configured")
        raise SystemExit(1)

    svc = _service()
    existing_tabs = _get_tabs(svc, sheet_id)
    print(f"✅ Connected — {len(existing_tabs)} tabs found")

    # Ensure _seed_log tab exists for idempotency tracking
    marker_tab = "_seed_log"
    if idempotent and marker_tab not in existing_tabs:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {
                "title": marker_tab,
                "gridProperties": {"rowCount": 100, "columnCount": 4},
            }}}]},
        ).execute()
        existing_tabs.add(marker_tab)
        print(f"   ➕ Created tracking tab: {marker_tab}")

    written = 0
    skipped = 0
    created_tabs = 0

    for tab, rows in RECOMMENDATIONS.items():
        fp = _fingerprint(rows)
        data_rows_only = rows[1:]  # exclude header
        count = len(data_rows_only)

        # Idempotency: skip if already seeded
        if idempotent and _seed_marker_exists(svc, sheet_id, marker_tab, fp):
            print(f"   ⏭️ {tab}: already seeded (fingerprint {fp}) — skipping")
            skipped += 1
            continue

        # Create tab if it doesn't exist
        if tab not in existing_tabs:
            print(f"   ➕ Creating tab: {tab}")
            svc.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"addSheet": {"properties": {
                    "title": tab,
                    "gridProperties": {"rowCount": max(count + 10, 100),
                                       "columnCount": max(len(rows[0]) + 2, 10)},
                }}}]},
            ).execute()
            existing_tabs.add(tab)
            created_tabs += 1

        # Check if tab already has a header — if not, write header + data
        # If yes, append data only (skip header to avoid duplication)
        has_header = _tab_has_header(svc, sheet_id, tab)
        if has_header:
            # Append data rows only (no duplicate header)
            _append_rows(svc, sheet_id, tab, data_rows_only)
            print(f"   ✅ {tab}: {count} rows appended (header preserved)")
        else:
            # New/empty tab: write everything including header
            _append_rows(svc, sheet_id, tab, rows)
            print(f"   ✅ {tab}: header + {count} rows written (new tab)")

        written += count

        # Record seed fingerprint
        if idempotent:
            _save_seed_marker(svc, sheet_id, marker_tab, fp,
                              f"{tab}: {count} rows")

    # Executive Brief metrics — always append
    if "Executive_Brief" in existing_tabs:
        print("   📊 Appending Executive_Brief metrics...")
        _append_rows(svc, sheet_id, "Executive_Brief",
                     [[k, v] for k, v in EXECUTIVE_BRIEF_METRICS.items()])
        print(f"   ✅ Executive_Brief: {len(EXECUTIVE_BRIEF_METRICS)} metrics appended")

    print(f"\n{'─' * 60}")
    print(f"🏁 تم الإدخال: {written} صف في {len(RECOMMENDATIONS) - skipped} تبويب")
    if created_tabs:
        print(f"   تبويبات جديدة أُنشئت: {created_tabs}")
    if skipped:
        print(f"   تبويبات تُخطّيت (مدخلة مسبقًا): {skipped}")
    print(f"\n💡 لمحة: هذا السكربت لا يحذف أي بيانات — يُضيف فقط.")
    print(f"   لإعادة الإدخال (تخطي الحماية): أزل التبويب _seed_log من الشيت.")


def export_markdown():
    """Export all recommendations as a local markdown file."""
    out_dir = os.path.join(BASE, "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "recommendations-preview.md")
    lines = ["# 🌱 التوصيات التشغيلية — معاينة", ""]
    for tab, rows in RECOMMENDATIONS.items():
        lines.append(f"## 📋 {tab}")
        lines.append("")
        headers = rows[0]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows[1:]:
            padded = list(row) + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(str(c) for c in padded[:len(headers)]) + " |")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"📄 معاينة Markdown → {os.path.relpath(path, BASE)}")


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    args = set(sys.argv[1:])
    if "--apply" in args:
        apply(idempotent="--idempotent" in args)
    elif "--markdown" in args:
        export_markdown()
    else:
        dry_run()


if __name__ == "__main__":
    main()

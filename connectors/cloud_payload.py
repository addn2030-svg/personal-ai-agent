# -*- coding: utf-8 -*-
"""ما يجوز أن يغادر الجهاز — فلتر واحد قبل أي رفع إلى السحابة.

المشكلة التي تحلّها هذه الوحدة
-----------------------------
`data/state.json` يحمل أقسامًا سريرية (`followups` = ورقة «متابعة مرضى» في
الشيت الرئيسي: رمز المريض · حالته السريرية · مواعيده). و`supabase_state.push`
كان يرفع **الحالة كاملة** — لا استثناء، ولا تنقية. أي أن أول عملية دفع بعد
ترحيل الشيت إلى SQL كانت سترفع صفوف المرضى إلى السحابة، وذلك يخالف الثابت
المعلن في المستودع: **البيانات السريرية لا تغادر الجهاز**.

وكذلك: النسخة السحابية مكانها نسخة مشتقة للاستعادة، فلا معنى أن تحمل معرّفات
شخصية (بريد · جوال · رقم ملف) لا يحتاجها الاسترجاع.

القرارات المتّخذة هنا
--------------------
1. **الاستثناء افتراضي** (لا العكس): القسم السريري يُحجب ما لم يُطلب خلاف ذلك
   صراحةً بـ`SUPABASE_INCLUDE_CLINICAL=1`. الوضع الآمن هو الافتراضي.
2. **المفتاح يبقى موجودًا بقائمة فارغة**: الاسترجاع يحتاج `REQUIRED_SECTIONS`
   كاملة، فالاستثناء يُفرغ القسم ولا يحذف مفتاحه.
3. **الإفراغ مُعلَن**: عدد الصفوف المحجوبة يُكتب في `meta` داخل النسخة نفسها،
   فيظهر في أي `show` أو استرجاع أن بيانات سريرية كانت موجودة ولم تُرفع. الحجب
   الصامت يجعل الناس تظن أن النسخة كاملة.
4. **الاستثناء قابل للتوسيع** بـ`SUPABASE_EXCLUDED_SECTIONS=followups,contacts`.
5. **الحجب في المضمون لا في اسم الحقل فقط**: كشف الترحيل الفعلي أن المحتوى
   السريري يتسرّب من أقسام غير سريرية — ملاحظة صوتية تقول «والمريض أحمد يحتاج
   مراجعة للخطة» داخل `voice`. لذلك يمرّ كل نص على `redact_clinical`، مع تمييز
   متعمَّد: «المرضى» في مؤشرات القسم (30 صفًا) إحصاء إداري مشروع ولا يُمس، أما
   «المريض أحمد…» فيُحجب لأنه يشير إلى فرد.
"""
from __future__ import annotations

import json
import os
import sys

from connectors.pii import redact_clinical, scrub_deep

# الاسم في الحالة = التسمية العربية في الشيت الرئيسي
CLINICAL_SECTIONS = ("followups",)


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def excluded_sections() -> tuple:
    """الأقسام المستثناة من الرفع. `SUPABASE_INCLUDE_CLINICAL=1` يلغي الاستثناء."""
    raw = os.environ.get("SUPABASE_EXCLUDED_SECTIONS")
    if raw is None or not raw.strip():
        sections = list(CLINICAL_SECTIONS)
    else:
        sections = [part.strip() for part in raw.split(",") if part.strip()]
    if truthy(os.environ.get("SUPABASE_INCLUDE_CLINICAL")):
        sections = [s for s in sections if s not in CLINICAL_SECTIONS]
    return tuple(sections)


def sanitize(state: dict, *, sections=None) -> tuple[dict, dict]:
    """يبني حمولة سحابية آمنة من كائن الحالة. يعيد (الحمولة, التقرير).

    لا يُعدّل الكائن الأصلي: الحالة المحلية تبقى مصدر الحقيقة كاملة.
    الترتيب مقصود: **إفراغ الأقسام المستثناة أولًا** ثم التنقية — فلا نحسب
    خلايا حُجبت داخل قسم كان سيُحجب كاملًا أصلًا، فيبقى التقرير معبّرًا عن
    ما نُقّي فعلًا من البيانات التي ستبقى.
    """
    sections = tuple(sections) if sections is not None else excluded_sections()
    report = {"withheld": {}, "redacted_cells": 0, "clinical_redactions": 0,
              "sections": list(sections)}

    payload = dict(state)

    # 1) إفراغ الأقسام المستثناة مع إبقاء مفاتيحها (الاسترجاع يحتاجها)
    for section in sections:
        rows = payload.get(section)
        if isinstance(rows, list) and rows:
            report["withheld"][section] = len(rows)
            payload[section] = []
        elif isinstance(rows, dict) and rows:
            report["withheld"][section] = len(rows)
            payload[section] = {}

    # 2) تنقية المعرّفات + حجب الإشارات السريرية في ما بقي
    payload, stats = scrub_deep(payload, clinical=True)
    report["redacted_cells"] = stats["pii"]
    report["clinical_redactions"] = stats["clinical"]

    # 3) إعلان الحجب داخل النسخة نفسها — الحجب الصامت يوهم بالاكتمال
    if report["withheld"] or stats["pii"] or stats["clinical"]:
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            payload["meta"] = meta
        if report["withheld"]:
            meta["cloud_withheld"] = "، ".join(
                f"{name}: {count}" for name, count in sorted(report["withheld"].items())
            )
        if stats["pii"]:
            meta["cloud_redacted_cells"] = stats["pii"]
        if stats["clinical"]:
            meta["cloud_clinical_redactions"] = stats["clinical"]
    return payload, report


def main(argv=None) -> int:
    """معاينة ما سيُرفع: تُقرأ الحالة المحلية ولا يُرسل شيء إلى الشبكة."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    import argparse

    parser = argparse.ArgumentParser(prog="cloud_payload", description="معاينة الحمولة السحابية")
    parser.add_argument("--preview", action="store_true", help="عرض ما سيُرفع بلا إرسال")
    parser.add_argument("--json", action="store_true", help="إخراج التقرير JSON")
    parser.add_argument("--state", default="", help="مسار state.json بديل")
    args = parser.parse_args(argv)

    from connectors.supabase_state import read_state, state_path
    try:
        state, _ = read_state(args.state or state_path())
    except FileNotFoundError:
        print(f"❌ لا يوجد ملف حالة: {args.state or state_path()}", file=sys.stderr)
        return 2

    payload, report = sanitize(state)
    if args.json:
        print(json.dumps({"report": report,
                          "withheld_sections": sorted(report["withheld"]),
                          "payload_sections": sorted(
                              key for key in payload if isinstance(payload.get(key), list))},
                         ensure_ascii=False, indent=2))
        return 0

    print("ما سيُرفع إلى Supabase:")
    print(f"  الأقسام المحجوبة : {report['withheld'] or 'لا شيء'}")
    print(f"  خلايا نُقّيت (معرّفات): {report['redacted_cells']}")
    print(f"  إشارات سريرية حُجبت  : {report['clinical_redactions']}")
    print(f"  إعلان الحجب في meta  : {payload.get('meta', {}).get('cloud_withheld', 'لا شيء')}")
    if report["withheld"]:
        print("\n  ℹ️  الأقسام المحجوبة تبقى كاملة في الجهاز؛ النسخة السحابية مشتقة لا مرآة.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
محاكاة يوم كامل مع المدير الشخصي — اختبار سير العمل بالكامل بلا متصفح.

    python3 -m level2.demo            # محاكاة يوم كامل (حالة معزولة مؤقتة — لا يلمس بياناتك)
    python3 -m level2.demo --live     # نفس المحاكاة على بياناتك الحقيقية (يكتب فعليًا!)

يستعرض سير العمل: بريف ← التقاط مهام ← استشارة قرار (خياران + 70%) ← حسم + إجراء
48 ساعة ← طاقة منخفضة ← بروتوكول الإرهاق ← نقطة ضعف ← عبارة جاهزة ← فلترة فكرة ←
انتظار ← إنجاز مهمة ← مراجعة أسبوعية.
"""
from __future__ import annotations

import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))


def banner(title: str) -> None:
    print("\n" + "═" * 74)
    print(f"  {title}")
    print("═" * 74)


def say(who: str, text: str, tag: str = "") -> None:
    label = f"🧑 أنت" if who == "user" else "🎙️ المدير"
    suffix = f"  [{tag}]" if tag else ""
    print(f"\n{label}{suffix}:")
    for line in text.split("\n"):
        print(f"   {line}")


def main() -> None:
    live = "--live" in sys.argv
    if not live:
        # حالة معزولة: المحاكاة لا تلوث بياناتك الحقيقية أبدًا
        os.environ["LEVEL2_STATE_PATH"] = os.path.join(
            tempfile.mkdtemp(prefix="l2demo-"), "state.json"
        )

    from level2 import agent
    from level2 import state as state_mod
    if not live:
        state_mod._store = None  # مخزن نظيف للمحاكاة
    get_store = state_mod.get_store

    print("╔" + "═" * 72 + "╗")
    print("║  اختبار سير العمل — يوم كامل مع المدير الشخصي (Level 2)              ║")
    print(f"║  الحالة: {'بياناتك الحقيقية (--live)' if live else 'معزولة مؤقتة (آمنة)'}")
    print("╚" + "═" * 72 + "╝")

    session = get_store().start_session("demo")

    # 1) البريف الصباحي
    banner("٠١:٠٠ — البريف الصباحي (قاعدة M3: أولويتان + قرار واحد)")
    r = agent.handle("بريف", session_id=session, channel="demo")
    say("user", "بريف", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 2) التقاط مهام صوتًا
    banner("٠٢:٠٠ — التقاط المهام (كل التزام يُحوَّل لمكان موثوق خلال دقيقتين)")
    for text in [
        "مهمة: تجهيز عرض العيادة المنزلية قبل 2026-10-08",
        "مهمة: مراجعة ملفات الأطباء قبل 12/10",
    ]:
        r = agent.handle(text, session_id=session, channel="demo")
        say("user", text, r["intent"])
        say("agent", r["reply"], r["mode"])

    # 3) استشارة قرار — قاعدة البديلين و70%
    banner("٠٣:٠٠ — استشارة قرار (M1: خياران فقط · M2: 70% يقين · مهلة 24 ساعة)")
    r = agent.handle("قرار: هل أطلق خدمة العيادة المنزلية هذا الشهر أم أؤجلها", session_id=session, channel="demo")
    say("user", "قرار: هل أطلق خدمة العيادة المنزلية هذا الشهر أم أؤجلها؟", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 4) نقطة ضعف — شلل التحليل
    banner("٠٤:٠٠ — نقطة ضعف: بطء الحسم (بروتوكول التعليمات البديلة)")
    r = agent.handle("أعاني من بطء الحسم في هذا القرار", session_id=session, channel="demo")
    say("user", "أعاني من بطء الحسم في هذا القرار", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 5) طاقة منخفضة — بروتوكول الإرهاق
    banner("٠٥:٠٠ — طاقة منخفضة (بروتوكول الهدوء والتعافي)")
    r = agent.handle("طاقتي 3", session_id=session, channel="demo")
    say("user", "طاقتي 3", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 6) عبارة جاهزة
    banner("٠٦:٠٠ — عبارة توجيهية جاهزة (مكتبة العبارات)")
    r = agent.handle("عبارة لرفض التزام جديد", session_id=session, channel="demo")
    say("user", "عبارة لرفض التزام جديد", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 7) فلترة فكرة جديدة
    banner("٠٧:٠٠ — فكرة جديدة (M6: صندوق الاحتمالات لا تشتيت)")
    r = agent.handle("فكرة: تطبيق توثيق الحالات السريرية بالذكاء الاصطناعي", session_id=session, channel="demo")
    say("user", "فكرة: تطبيق توثيق الحالات السريرية بالذكاء الاصطناعي", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 8) الانتظار
    banner("٠٨:٠٠ — الحلقات المفتوحة (انتظار)")
    r = agent.handle("الانتظار", session_id=session, channel="demo")
    say("user", "الانتظار", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 9) إنجاز مهمة + دليل
    banner("٠٩:٠٠ — إنجاز مهمة (طلب دليل الإنجاز)")
    r = agent.handle("أنجزت عرض العيادة المنزلية", session_id=session, channel="demo")
    say("user", "أنجزت عرض العيادة المنزلية", r["intent"])
    say("agent", r["reply"], r["mode"])

    # 10) مراجعة أسبوعية
    banner("١٠:٠٠ — المراجعة الأسبوعية (M9: قياس العملية لا النتيجة فقط)")
    r = agent.handle("مراجعة أسبوعية", session_id=session, channel="demo")
    say("user", "مراجعة أسبوعية", r["intent"])
    say("agent", r["reply"], r["mode"])

    # النتيجة
    banner("اختبار الحالة النهائية على القرص (استمرارية بعد إعادة التشغيل)")
    from level2.state import Level2Store
    st2 = Level2Store(get_store().path)  # إعادة فتح كما يفعل الخادم عند الإقلاع
    s = st2.weekly_stats()
    print(f"""   المهام المفتوحة .......... {s['tasks_open']}
   المهام المنجزة ............ {s['tasks_completed']}
   القرارات المعلقة .......... {s['decisions_pending']}
   متوسط الطاقة .............. {s['energy_avg']:.1f}/10
   صندوق الاحتمالات .......... {len(st2.snapshot()['possibilities'])}
   ملف الحالة ................ {st2.path}
   ✅ كل شيء محفوظ — أعد تشغيل الخادم وستجده كما هو.""")

    print("\n" + "═" * 74)
    print("  انتهت المحاكاة — جرّب بنفسك صوتًا: python3 -m level2.server ثم 🎙️")
    print("═" * 74)


if __name__ == "__main__":
    main()

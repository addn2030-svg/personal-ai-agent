# -*- coding: utf-8 -*-
"""
Social Triage — فرز رسائل المنصات (Phase 1 يدوي):
  python3 engine/social_triage.py "نص الرسالة" [--from "اسم المرسل"]
يصنف P1-P4 + النية، وإن احتاج ردًا: يسجل مسودة في طابور الاعتماد (لا إرسال).
"""
import datetime as dt
import hashlib
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()


def norm(t):
    return (t or "").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")


def triage(text):
    s = norm(text)
    p, intent = "P4", "other"
    if re.search(r"شكوي|اشتكي|شكوى|غاضب|سيئ|استرجاع|اخطاء|مشكلتي|مستاء", s):
        p, intent = "P1", "complaint"
    elif re.search(r"عاجل|اليوم|حالا|ضروري جدا", s):
        p, intent = "P1", "urgent"
    elif re.search(r"حجز|موعد|احجز", s):
        p, intent = "P2", "booking"
    elif re.search(r"سعر|كم|بكم|عرض", s):
        p, intent = "P2", "pricing"
    elif re.search(r"شراكه|تعاون|مركز|شركه|فرصه", s):
        p, intent = "P2", "collaboration"
    elif re.search(r"خدمه|استفسار|علاج طبيعي|زياره", s):
        p, intent = "P2", "service_inquiry"
    elif re.search(r"الم|وجع|اصابه|تقييم", s):
        p, intent = "P2", "clinical_question"
    elif re.search(r"تذكير|متابعه|وين وصلنا", s):
        p, intent = "P3", "follow_up"
    elif re.search(r"شكرا|ممتاز|يعطيك|رائع", s):
        p, intent = "P4", "testimonial"
    return p, intent


NEEDS_REPLY = {"P1", "P2", "P3"}


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    text = sys.argv[1]
    sender = ""
    if "--from" in sys.argv:
        sender = sys.argv[sys.argv.index("--from") + 1]
    p, intent = triage(text)
    print(f"📶 التصنيف: {p} | النية: {intent}")
    if p == "P1":
        print("   ⚠️ قاعدة P1: لا رد فوري على الغضب — مسودة تمر بالاعتماد فقط.")
    if p not in NEEDS_REPLY:
        print("   لا يحتاج ردًا — سُجل للعلم.")
        log_event("SOCIAL_TRIAGED", priority=p, intent=intent)
        return

    draft = (f"مسودة رد على {sender or 'المرسل'} ({p}/{intent}):\n"
             f"«شكرًا لرسالتك{'، ' + sender if sender else ''}. "
             + ("بخصوص طلبك، يسعدنا خدمتك — هل يناسبك تواصل قصير اليوم أو غدًا لترتيب التفاصيل؟"
                if intent != "complaint" else
                "نقدّر إطلاعك، ونأخذ ملاحظتك بجدية — سيتواصل معك عبدالرحمن شخصيًا خلال 24 ساعة.") + "»")
    st = Store(); S = st.rows_all()
    h = hashlib.sha256(draft.encode()).hexdigest()[:16]
    if not any(a.get("content_hash") == h for a in S["action_queue"]):
        S["action_queue"].append({"action_id": f"A-{len(S['action_queue'])+1:03d}",
                                  "type": "send_social_reply", "channel": "social",
                                  "content": draft, "content_hash": h, "status": "PENDING_APPROVAL",
                                  "created_at": TODAY.isoformat(),
                                  "expires_at": (TODAY + dt.timedelta(days=2)).isoformat(),
                                  "approved_at": None, "executed_at": None})
        st.commit(S, "social_draft", priority=p, intent=intent)
        log_event("SOCIAL_TRIAGED", priority=p, intent=intent, draft=True)
        print(f"📝 مسودة رد أُدرجت في طابور الاعتماد — راجعها من تيليجرام /approve")
    else:
        print("المسودة موجودة مسبقًا (idempotent) ✅")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Level 2 — المدير الشخصي التنفيذي (Executive Personal Manager, Live-Talking Edition).

Self-contained, local-first personal manager agent:
  • لا Google Sheets  — الحالة في ملف JSON محلي (data/level2_state.json)
  • لا Supabase       — لا نسخ سحابي ولا مفاتيح
  • لا API خارجي      — يعمل دون أي مفتاح؛ نموذج لغوي اختياري (محلي/OmniRoute) بلا اعتماد
  • لا Git/GitHub     — لا CI ولا نشر؛ يعمل من مجلد المشروع مباشرة

Autonomy level = L2 (تنفيذ داخلي قابل للعكس + تقرير):
كل تأثير خارجي (رسالة، دفع، نشر) يبقى اقتراحًا لا ينفذ أبدًا من تلقاء نفسه.

Run:
    python3 -m level2.server             # واجهة الصوت في المتصفح (الوضع الأساسي)
    python3 -m level2.telegram_bridge    # جسر تيليجرام (اختياري، عند توفر التوكن)
    python3 -m level2.migrate            # استيراد بياناتك من النظام القديم/الشيت
"""

VERSION = "2.0.0"

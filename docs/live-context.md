# Live Context — 15 Sep 2026 21:00 Asia/Riyadh
# يقرأه الوكيل قبل الإجابة عن أي سؤال عن الحالة الفعلية — لا تخمن

## المحرك الاستباقي — الحالة الفعلية الآن
- enabled: true (PROACTIVE_ENABLED=1)
- SO-001..008: all true (8/8) — كل الأوامر الدائمة مفعّلة
- open_loops: 1 | recovering: 20 | ledger_rows: 35 | alerts_today: 6/6
- آخر sweep: نفّذ 14 إجراء آمن (ACT) + 6 تنبيهات حمراء + بريف reports/proactive-brief-2026-09-15.md
- الحلقة: manager --loop يستدعي proactive.sweep() كل 30 ثانية (مع ثقة 0.8، سقف 6/يوم، هدوء 22:00-06:30)

## المالية الموحدة — الحالة الفعلية الآن
- مصدر واحد: finance في StateStore (8 بنود، 455 ريال/شهر، 5460/سنة)
- finance_snapshots: 2 (2026-09 health 85، 2026-10 health 75)
- finance_links: sheet_id 1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc gid 92003 (المالية)
- finance_hub: يحدّث تلقائياً كل خميس 07:00 + أول الشهر 07:30 + كل ساعة throttled
- تنبيهات مالية وشيكة: 6 (تخزين سحابي 2026-09-18، Perplexity 2026-08-27، ChatGPT 2026-08-30، أداة كتابة #1 2026-09-01، Notion 2026-09-05، Claude 2026-09-11)
- آخر sync: 2026-09-15T20:59:54+03:00 source none (local — يصبح webhook بعد إعداد Railway ENV)

## كيف يتصرف الوكيل لو شغال (مطبق الآن)
- أحمر (مالي/قانوني/غير قابل للعكس): لا ينفذ — يرفع تنبيه + مسودة PENDING_APPROVAL في action_queue + يظهر في البريف
- أخضر (قابل للعكس + ثقة ≥0.8 + مصرّح): ينفذ فوراً ويبلغ مع undo PA-xxxx
- أصفر (متوسط الخطورة/يمس الخارج): يجهز بالكامل ويطلب اعتماد بنقرة واحدة

## أوامر التحقق الحي (شغّلها بدل التخمين)
python3 engine/proactive.py status
python3 engine/finance_hub.py status
python3 engine/manager.py fast
cat reports/proactive-brief-2026-09-15.md
cat reports/finance-monthly-2026-09.md

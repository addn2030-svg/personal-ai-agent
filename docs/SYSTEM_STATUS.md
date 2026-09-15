# System Status — أمر واحد يكشف كل شيء

إذا سُئلت عن الطبقات النائمة أو الجدولة أو الحالة الفعلية، شغّل:

```bash
python3 engine/system_status.py --layers --schedule
python3 engine/system_status.py --finance
python3 engine/system_status.py --proactive
```

## المخرجات الحالية (15 Sep 2026 22:05 Asia/Riyadh)

### الطبقات (14 طبقة)
- ✅ store — StateStore single source
- ✅ manager fast/full — fast 15m + full 06:00 + dormant loop + finance_hub + trust heartbeat
- ✅ scheduler — 11 jobs (daily/weekly/monthly) via manager --loop
- ✅ proactive — enabled true 8/8 SO, alerts 6/6
- ✅ finance_hub v2.0 — 8 rows, 2 snapshots, link true — auto: Thu 07:00 + 1st 07:30 + hourly
- ✅ asset_registry, backup_verify, change_intelligence, observability, trust_dashboard — activated v2.0 (now in manager loop)
- ✅ rag, context_service, chief_of_staff, approve C2

كل الطبقات النائمة التي كانت MISSING الآن **activated v2.0** — موثقة في `docs/DORMANT_ACTIVATION_2026-09-15.md`

### الجدولة
- daily: 06:45 morning_brief, 07:30 focus_block, 16:00 supervisor_close (أحد-خميس), 20:30 audio_digest
- weekly: الأحد 07:15 ops, الثلاثاء 14:00 DHS, **الخميس 07:00 finance**, الجمعة 16:00 mindmap
- monthly: 28 تقرير إنتاجية, **1 مؤشر صحة مالية**, آخر يوم أرشفة سياق

### المالية
- finance_rows 8, total 455, snapshots 2 (2026-09 health 85, 2026-10 health 75), link 1ZXmC...

### الاستباقية
- enabled true, 8 SO, ledger 35, recovering 20, open_loops 1

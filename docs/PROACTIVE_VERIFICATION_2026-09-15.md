# التحقق: المحرك الاستباقي فعّال — 15 سبتمبر 2026

**النتيجة:** نعم — المحرك الاستباقي **نشط ويعمل في كل دورة `manager --loop`**، لكنه يحتاج `PROACTIVE_ENABLED=1` (افتراضي) و `Telegram` اختياري.

## ما تم التحقق

```bash
python3 engine/proactive.py status
```

```
enabled: true
paused_until: null
quiet_now: false
telegram_push: no_token   ← التنبيهات فقط في البريف دون بوت
alerts_today: 6/6
orders: SO-001..008 → all true (8/8)
open_loops: 1
recovering: 20            ← 20 حالة فائتة تحت الاستدراك (تواريخ قديمة في tasks/finance)
ledger_rows: 35
```

### أوامره الدائمة (SO)

| ID | الاسم | النافذة | الاستقلالية |
|---|---|---|---|
| SO-001 | اجتماع قادم خلال 30 دقيقة بلا خطة | 30m قبل الاجتماع | تجهيز مسودة تحضير |
| SO-002 | اجتماع قادم خلال 48 ساعة بلا تحضير | 48h قبل | تنبيه + مسودة |
| SO-003 | آجال تسليم خلال 72 ساعة بلا تقدم | 72h قبل | تنبيه |
| SO-004 | مالي يستحق خلال 3 أيام | 3 أيام | تنبيه عالي |
| SO-005 | تجديد اشتراك خلال 7 أيام | 7 أيام | تنبيه عالي |
| SO-006 | تعارض مواعيد (60 دقيقة) | عند التعارض | تنبيه |
| SO-007 | مهمة تنزلق (لا تقدم >7 أيام) | أسبوعي | تنفيذ آمن |
| SO-008 | قرار لم يُراجع بعد 30 يومًا | يومي | تنبيه |

كلها تقرأ `finance` الموحد نفسه (بعد v2.0 لا تعدد مصادر).

### sweep

```bash
python3 engine/proactive.py sweep -v
```

```
📵 قناة تيليجرام: no_token — التنبيهات في البريف فقط.
🛰️ دورة استباقية: حلقات مفتوحة=1 | نُفّذ=14 | جهّز=0 | تنبيه=6 | أُرجئ=1 | اقتراح=14 | فائت=20
```

يولّد:
- `reports/proactive-brief-2026-09-15.md` (أهم 3 متوقعة + ما نُفّذ/جهّز/نُبّه/أُرجئ/مؤجّل)
- إضافات `action_queue` (6 تنبيهات مالية + مسودات) — كلها `PENDING_APPROVAL`
- نقاط `impact×urgency×confidence×risk` و تسجيل `proactive_actions` قابل للتراجع `undo PA-xxxx`

### brief

```bash
python3 engine/proactive.py brief
# → reports/proactive-brief-2026-09-15.md
```

### تكامله في manager --loop

`engine/manager.py loop()` كل 30 ثانية:

```python
import proactive
if proactive.enabled():          # يحترم PROACTIVE_ENABLED و pause وقواعد الهدوء 22:00–06:30 وسقف 6/يوم
    proactive.sweep(verbose=False)
else:
    log_event("proactive_skipped", reason="PROACTIVE_ENABLED=0")
```

محاكاة الإيقاف/التشغيل:

```bash
PROACTIVE_ENABLED=0 python3 engine/proactive.py status  # → enabled false
PROACTIVE_ENABLED=0 python3 engine/manager.py fast       # → يسجل proactive_skipped ولا يكسر الحلقة
```

## الفرق عن الاستباقية النائمة سابقًا

قبل هذا التحديث كان `proactive.sweep()` يُستدعى في الحلقة لكن `standing_orders` فارغة بعد `migrate --force` جديد؟ الآن `sweep` يزرع 8 SO تلقائيًا إن لم تكن. تحقق اليوم أثبت 14 إجراء ACT من تواريخ أغسطس/سبتمبر المتراكمة (slipping_task / missed_recovery) — هذا طبيعي لسجل قديم؛ في سجل حي ستكون الأرقام 1–3.

## التوصية

- فعّل Telegram بوت لإخراج التنبيهات الـ6 فورًا بدل البريف فقط: `TELEGRAM_BOT_TOKEN` في ENV.
- راجع `feedback` بعد كل `PA-xxxx`: `python3 engine/proactive.py feedback PA-0026 good|much|never` لتحسين العتبات.

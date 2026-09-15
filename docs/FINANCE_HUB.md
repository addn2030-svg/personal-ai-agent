# Finance Hub الموحد v2.0 — 15 سبتمبر 2026

> مصدر واحد، تحديث تلقائي شهري، رابط حي مع شيت خارجي، لا أسرار في الكود.

## الفكرة

كان هناك تشتت قديم: `finance` + `finance_ebsi` كتبويبين منفصلين مع حسابات منفصلة. اليوم **مصدر واحد هو الحقيقة**: `finance` في `StateStore`. `finance_ebsi` يُهاجر تلقائيًا إليه عند أول sync (ويُبقى للتوافق فقط).

## المكون

`engine/finance_hub.py` — 725 سطر، مسؤول عن:

- **توحيد** `finance` + أي صفوف خارجية (بدون حذف محلي، يضيف أو يحدّث فقط)
- **سحب خارجي** عبر 3 مسارات حسب المتاح (بالترتيب):
  1. **Webhook الآمن** (الأفضل للإنتاج داخل Railway) — `GOOGLE_SHEETS_WEBHOOK_URL` + `GOOGLE_SHEETS_WEBHOOK_SECRET` مع Apps Script `google_sheets_webhook.gs` (`SPREADSHEET_ID = FINANCE_SHEET_ID`)
  2. **CSV العام** — `https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid={GID}` إذا كان الشيت `Anyone with link → Viewer`
  3. **ملف يدوي** — `data/finance-external.csv` (تضع فيه `File → Download → CSV` من الشيت يدويًا)

- **لقطة شهرية** — `reports/finance-monthly-YYYY-MM.md/.html` وصف `finance_snapshots` (يحتفظ بآخر 24 شهرًا). تُحسب فيها:
  - `total_monthly / total_yearly`, `by_type`, `unused_count`, `savings_potential`, `health_index`

## الجدولة

| متى | ماذا | أين |
|---|---|---|
| **كل خميس 07:00 Asia/Riyadh** | `weekly.finance_thursday_0700` — يزامن finance_hub.sync ثم يولّد مسودة مراجعة ميزانية | `engine/scheduler.py` → `action_queue` |
| **أول كل شهر 07:30** | `monthly.monthly_finance_health_1st` — يزامن finance_hub.auto_update ثم يولّد مؤشر الصحة + يبني/يحدّث اللقطة | `engine/scheduler.py` |
| **كل ساعة (throttled)** | `manager --loop` → `finance_hub.auto_update(force=False)` | `engine/manager.py` (كل دورة سريعة، throttle 1h) |
| **كل 06:00** | `manager full_cycle` → `finance_hub.auto_update` + كشف الأنماط | `engine/manager.py` |

كل مسودات scheduler/manager هي **PENDING_APPROVAL** فقط — تُعتمد عبر `engine/approve.py approve A-XXX --hash ...`

## التخزين

`engine/store.py` SECTIONS الآن تشمل:

```python
"finance_snapshots",  # لقطات شهرية (24 شهر)
"finance_links",      # رابط الشيت الخارجي {sheet_id, gid, linked_at}
```

مع `manager_markers`: `finance_last_sync`, `finance_last_source`, `finance_external_rows`, `finance_link_sheet`

## الاستخدام

```bash
# حالة الربط
python3 engine/finance_hub.py status

# ربط شيت خارجي (الإنتاج: ضعه في ENV FINANCE_SHEET_ID بدلًا من link)
python3 engine/finance_hub.py link 1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc
# أو مع GID محدد
python3 engine/finance_hub.py link SHEET_ID GID

# سحب ودمج الآن (force لتجاوز throttle الساعة)
python3 engine/finance_hub.py sync --force

# لقطة شهرية يدوية
python3 engine/finance_hub.py snapshot --force

# تقرير كامل (stdout + reports/finance-monthly-*.md)
python3 engine/finance_hub.py report

# تحديث كامل (sync + snapshot إذا استحق)
python3 engine/finance_hub.py auto --force

# إزالة الربط
python3 engine/finance_hub.py unlink
```

### ENV (Railway / محلي)

```env
FINANCE_SHEET_ID=1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc
FINANCE_SHEET_GID=          # اختياري
GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
GOOGLE_SHEETS_WEBHOOK_SECRET=...  # نفسه في Code.gs AGENT_SECRET
FINANCE_HUB_ENABLED=1       # 0 لتعطيل مزامنة finance_hub في حلقة المدير
```

للمزامنة عبر webhook انشر `google_sheets_webhook.gs` كـ Web App (Anyone → Execute as you) واضبط `SPREADSHEET_ID`.

### الربط اليدوي (offline) — للبيئة المعزولة

إذا كانت الشبكة تحجب `docs.google.com` (كما في sandbox):

```bash
# من الشيت: File → Download → CSV (تبويب المالية)
cp ~/Downloads/المالية.csv data/finance-external.csv
python3 engine/finance_hub.py sync --force
```

## التوافق

- يقرأ `engine/proactive.py` SO-004/SO-005 نفس `finance` الموحد — لا شيت مكرر
- يقرأ `engine/scheduler.py` نفس `finance` + `finance_snapshots` للمؤشر/Ledger
- `migrate_ebsi` لمرة واحدة: ينسخ صفوف `finance_ebsi` الناقصة إلى `finance` مع ملاحظة `مُهاجر من finance_ebsi`

## التحقق 15SEP2026

```
python3 engine/finance_hub.py status
# → finance_rows: 8, total_monthly: 455, snapshots: 2 (2026-09, 2026-10), external_source: none/local_file, hint: ...

python3 engine/manager.py fast    # → متأخر=5 | إجراءات=5 | ...
python3 engine/manager.py full    # → البريف + المراجعة + Dashboard
python3 engine/scheduler.py dispatch --date 2026-10-01 --at 07:30  # → monthly_finance_health produced
python3 engine/scheduler.py dispatch --date 2026-09-17 --at 07:30  # → finance_thursday produced
python3 engine/proactive.py status  # → enabled true, 8/8 SO, ledger 35
python3 engine/proactive.py sweep   # → open_loops 1, recovering 20, brief generated
```

## الحوكمة

- لا إرسال خارجي تلقائي أبدًا — كل مخرجات finance_hub تذهب `action_queue` أو `reports/` أو `state.json`
- throttle ساعة على sync لتجنب الضغط
- `TRUST_HEARTBEAT_ENABLED` و `FINANCE_HUB_ENABLED` للطوارئ

---

*تصميم: arena/01a0a62d-personal-ai-agent — 15SEP2026 — المنطقة Asia/Riyadh*

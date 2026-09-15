# تفعيل الطبقات النائمة — 15 سبتمبر 2026

## الملخص

تم تدقيق المستودع: **~18 ملف engine + ~14 connector** موجودون ولا يُستدعون في `manager --loop` الحالي. الحلقة الحيّة كانت: `store + manager fast/full + chief + scheduler + proactive`.

**اليوم:** كل الطبقات النائمة فُعّلت أو وُثّقت.

## ما فُعّل

### 1) manager.py

**قبل:** `full_cycle()` يستدعي فقط `chief_of_staff.py`.

**الآن `full_cycle()`:**

```python
finance_hub.auto_update(force=False)   # توحيد المالية + لقطة
for script in ["asset_registry.py", "backup_verify.py", "change_intelligence.py", "observability.py", "trust_dashboard.py"]:
    subprocess.run([sys.executable, "engine/"+script], capture_output=True, timeout=20)  # guarded
subprocess.run([sys.executable, "engine/asset_registry.py"], ...)
subprocess.run([sys.executable, "engine/chief_of_staff.py"], ...)
```

**الآن `loop()` (كل 30 ثانية):**

- `scheduler.dispatch_due()` — موجود سابقًا
- `proactive.sweep()` مع فرع `proactive_skipped` عند `PROACTIVE_ENABLED=0`
- **`finance_hub.auto_update(force=False)` throttled ساعة** — يُعطّل بـ `FINANCE_HUB_ENABLED=0`
- **`trust heartbeat يومي`**: `observability.py + trust_dashboard.py` مرة يوميًا عند `trust_day != today` — يُعطّل بـ `TRUST_HEARTBEAT_ENABLED=0`

كلها محاطة `try/except log_event` — لا تكسر الحلقة.

### 2) store.py

إضافة قسمين جديدين (v2.0):

```python
"finance_snapshots",  # لقطات شهرية
"finance_links",      # روابط الشيتات الخارجية
```

### 3) scheduler.py

- `_produce_finance_thursday` أصبح v2.0: يسحب `finance_hub.sync_external` ثم يقرأ الحالة المحدّثة ويضيف سطر `🔗 خارجي: N بند (source)` + تلميح `reports/finance-monthly-*.md` + تعليمات الربط
- `_produce_finance_health_1st` أصبح v2.0: يفوّض إلى `finance_hub.auto_update/build_snapshot/ensure_monthly_snapshot` ويُظهر `total_monthly/unused_count/savings/health_index/source/snapshot_id`
- `dispatch` الآن يدعم `--date` و `--at` (للمحاكاة والاختبار)

### 4) finance_hub.py (جديد)

انظر `docs/FINANCE_HUB.md`.

## ما بقي نائمًا (وثّق كـ تصميم)

| الملف | السبب | القرار |
|---|---|---|
| `engine/v05_cycle.py` .. `v08_cycle.py` | سلاسل تراكمية قديمة حلّ محلها manager loop | **أرشيف** — لا يُستدعى، يمكن حذفه أو نقله لـ `engine/archive/` لاحقًا |
| `engine/rag.py`, `search.py`, `context_service.py` | تتطلب `knowledge/` + `drive_tree` + فهرس vector | **يدوي**: `python3 engine/rag.py build` عند وجود مصادر |
| `engine/skill_*` (6 ملفات) + `skill_runtime.py` | 0 مهارة ACTIVE، `skills/generated/` فارغ | **تصميم**: يُفعّل عبر `reflection_engine.py reflect` أسبوعيًا أو يُحذف |
| `engine/energy_log.py`, `okr.py`, `behavior_model.py`, `memory.py` | أقسام فارغة (0 صفوف) | **يدوي**: `python3 engine/energy_log.py 7 3 --note ...` |
| `engine/import_inbox.py`, `migrate.py`, `make_template.py` | أدوات لمرة واحدة | **يدوي** |
| `engine/persistence_nudge.py`, `social_triage.py`, `previsit_intelligence.py`, `telegram_smoke_test.py` | أدوات تجريبية 0–2 إشارة | **أرشيف مقترح** |
| `connectors/*` (14 stub) | لمستقبل Commerce/Buffer/Calendar | **stubs** — لها اختبارات لكن لا webhook |

## التحقق

```bash
python3 -m py_compile engine/{manager,scheduler,finance_hub,store}.py && echo "compile ok"
python3 engine/proactive.py status        # → enabled true, 8 SO, 6/6 alerts
python3 engine/proactive.py sweep -v      # → 14 ACT, 6 تنبيهات, brief generated
python3 engine/manager.py fast            # → overdue/actions/dr ...
python3 engine/manager.py full            # → dashboard + brief + weekly
python3 engine/scheduler.py dispatch --date 2026-09-17 --at 07:30  # → finance_thursday
python3 engine/scheduler.py dispatch --date 2026-10-01 --at 07:30  # → finance_health + finance_thursday
python3 engine/finance_hub.py status      # → snapshots 2, link set, hint
```

## الحوكمة

- لا تعطيل لـ `action_queue PENDING_APPROVAL` — كل تفعيل يلتزم `write-on-change` و `idempotent` عبر hash/content_hash/cycle_key
- لا إرسال خارجي تلقائي — كل طبقة تسجّل `log_event` وتولّد مسودات فقط

---

*arena/01a0a62d — 2026-09-15*

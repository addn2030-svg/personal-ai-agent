# -*- coding: utf-8 -*-
"""مرحلة التشغيل التدريجي (Rollout) — تشغيل متوازٍ بلا توقف، مع تراجع فوري.

الغرض: تشغيل طبقة Supabase الجديدة **بالتوازي** مع سير العمل القائم، خطوةً خطوة،
حتى تُثبت نفسها بالأدلة قبل أن تعتمد عليها. لا شيء في النظام القديم يُوقف أو
يُغيَّر أثناء ذلك.

المراحل (لا تُقفز، ولا تُختصر):

    0 dormant  — مُثبَّتة ولا تفعل شيئًا. لا شبكة ولا كتابة. خط الأساس الآمن.
    1 shadow   — قراءة ومقارنة فقط (reconcile). **صفر كتابة**؛ تجمع أدلة الانحراف.
    2 canary   — الكتابة بأمر بشري صريح فقط (CLI أو /backup_now). الأتمتة ما تزال مطفأة.
    3 dual     — الأتمتة اليومية تعمل، وسير العمل القديم يعمل كما هو بلا أي تغيير.
    4 primary  — الطبقة الجديدة هي المسار الافتراضي لشأنها (النسخ التلقائي)،
                 فيصبح الخطأ اليدوي المتوارث اختياريًا — لا يُحذف.

قاعدتان حاكمتان:

1. **الأتمتة مقيَّدة بالمرحلة؛ الإنسان لا يُمنع أبدًا.** أي أمر صريح من الطرفية
   يعمل في أي مرحلة (ولو كانت `dormant`) — فلا نمنع المالك من أخذ نسخة احتياطية
   وقت الحاجة، ولا نحبسه خلف راية إعداد.
2. **الفشل ينغلق على الأأمن.** ملف المرحلة تالف أو مفقود ⇒ تُقرأ `dormant`،
   فيتوقف كل شيء تلقائيًا بلا استثناء يصل إلى حلقة المدير.

الترقية تحتاج **دليلًا** لا نيّة: عدد تشغيلات ناجحة + انحراف صفري، ومع المرة
الأخيرة توقيع بشري صريح (رمز مطابق حرفيًا)، تمامًا كنمط `MONEY_AUTOPAY_ACK`.
والتراجع متاح دائمًا وفوري — بلا شرط ولا دليل.

أوامر:
  python3 -m engine.rollout status        # المرحلة الحالية والقدرات والبوابة
  python3 -m engine.rollout plan          # ماذا تفعّل كل مرحلة · وماذا لن يُلغى أبدًا
  python3 -m engine.rollout simulate      # محاكاة بلا تغيير أي شيء
  python3 -m engine.rollout reconcile     # مقارنة المرآة بالحالة (قراءة فقط)
  python3 -m engine.rollout advance       # ترقية خطوة واحدة (إن اجتازت البوابة)
  python3 -m engine.rollout rollback --to shadow --reason "خطأ متكرر"
  python3 -m engine.rollout kill          # مفتاح إيقاف فوري ⇒ dormant
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

PHASES = ["dormant", "shadow", "canary", "dual", "primary"]

PHASE_LABEL = {
    "dormant": "0 · خاملة (لا شيء يعمل)",
    "shadow": "1 · ظلّ (قراءة ومقارنة فقط)",
    "canary": "2 · تجريبية (كتابة بأمر بشري)",
    "dual": "3 · متوازية (أتمتة + القديم يعمل)",
    "primary": "4 · أساسية (النسخ التلقائي هو الافتراضي)",
}

# القدرات المقيَّدة: تخصّ **الأتمتة** وحدها. الأوامر البشرية الصريحة خارج هذا الجدول.
CAPABILITIES = {
    "dormant": {"automation_read": False, "automation_write": False},
    "shadow": {"automation_read": True, "automation_write": False},
    "canary": {"automation_read": True, "automation_write": False},
    "dual": {"automation_read": True, "automation_write": True},
    "primary": {"automation_read": True, "automation_write": True},
}

# شروط الترقية — الأدلة المطلوبة لكل خطوة.
#
# ملاحظة مقصودة: «انحراف صفري» لا يُشترط إلا **بعد** أن تبدأ الكتابة. في مرحلة الظلّ
# لا يُكتب شيء، فوجود انحراف أمر متوقع ومحتوم؛ واشتراط صفره هناك يعني بوابة لا تُجتاز
# أبدًا (وحلقة مفرغة: لا نكتب حتى نتأكد، ولا نتأكد حتى نكتب). لذلك:
#   • إلى shadow  ⇒ يكفي أن أداة المقارنة تعمل وتُسجّل نتائجها.
#   • إلى canary  ⇒ نفس الشرط.
#   • إلى dual    ⇒ هنا فقط يُشترط أن تكون آخر مقارنة بعد الكتابة اليدوية بلا انحراف.
#   • إلى primary ⇒ نفسها + توقيع بشري.
GATE_REQUIREMENTS = {
    "shadow": {"runs": 2},
    "canary": {"runs": 2},
    "dual": {"runs": 3, "max_drift": 0, "max_errors": 0},
    "primary": {"runs": 5, "max_drift": 0, "max_errors": 0, "ack": True},
}
# حدود دنيا صارمة في الكود: متغيرات البيئة تخفض الطلب **أبدًا** — ترفعه فقط.
GATE_FLOORS = {"runs": 2, "max_drift": 0, "max_errors": 0}

# الترقية الأخيرة تحتاج توقيعًا بشريًا حرفيًا — لا يكفي أن «كل شيء يبدو جيدًا».
PRIMARY_ACK = "I_VERIFY_SUPABASE_LAYER_IS_STABLE"
ACK_ENV = "SUPABASE_PRIMARY_ACK"

# ما **لن** يُلغى في أي مرحلة — يُطبع في `plan` ويُختبر في الاختبارات.
NEVER_RETIRED = [
    "data/state.json يبقى مصدر الحقيقة الوحيد (لا يصبح Supabase مرجعًا).",
    "بوابة الاعتماد action_queue وكل ما يمر بها يبقى كما هو.",
    "حلقة المدير (manager --loop) تعمل بلا توقف في كل المراحل.",
    "أوامر الطوارئ اليدوية تبقى متاحة: push · restore · stats · /backup_now.",
    "لا حذف لأي بيانات في Supabase عند التراجع (النسخ تبقى؛ التراجع لا يمحو أثرًا).",
]

ROLLOUT_FILE = ".rollout.json"


# ------------------------------------------------------------------- storage
def data_dir() -> str:
    return os.environ.get("AI_OS_DATA_DIR", os.path.join(BASE, "data"))


def path() -> str:
    return os.path.join(data_dir(), ROLLOUT_FILE)


def log_event(event: str, **details) -> None:
    """تدقيق يُكتب إلى المسار **المحلول وقت النداء** (لا وقت الاستيراد).

    سبب عدم استخدام `store.log_event`: هذا الأخير يحسب `AUDIT_PATH` مرة واحدة عند
    الاستيراد، فلو تغيّر `AI_OS_DATA_DIR` (كإعادة نشر، أو اختبار) كُتب الدليل في
    مكان آخر — وبوابة الترقية تقرأ ملف التدقيق الحالي. الأدلة يجب أن تُكتب حيث
    تُقرأ بالضبط، وإلا صارت البوابة تقرأ فراغًا وتظن أن لا شيء جرى.
    """
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "event": event}
    entry.update(details)
    try:
        target = os.path.join(data_dir(), "audit.jsonl")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 - التدقيق لا يُسقط أي عملية
        pass


def _default_state() -> dict:
    return {
        "phase": "dormant",
        "since": dt.datetime.now().isoformat(timespec="seconds"),
        "changed_by": "default",
        "reason": "لم تُضبط أي مرحلة بعد — الوضع الافتراضي الآمن",
        "history": [],
    }


def load() -> dict:
    """يقرأ حالة المرحلة. أي عطل ⇒ `dormant` (فشل ينغلق على الأأمن)."""
    try:
        with open(path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return _default_state()
    except (OSError, ValueError):
        broken = _default_state()
        broken["reason"] = "ملف المرحلة تالف — أُعيد الوضع الآمن dormant"
        broken["corrupt"] = True
        return broken
    if not isinstance(data, dict) or data.get("phase") not in PHASES:
        broken = _default_state()
        broken["reason"] = "مرحلة غير معروفة في الملف — أُعيد الوضع الآمن dormant"
        broken["corrupt"] = True
        return broken
    data.setdefault("history", [])
    return data


def _write(data: dict) -> None:
    """كتابة ذرّية: لا يبقى ملف نصف مكتوب لو انقطع التيار لحظة التبديل."""
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp = f"{target}.tmp-{os.getpid()}"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temp, target)


def current_phase() -> str:
    return load()["phase"]


def index(phase: str | None = None) -> int:
    return PHASES.index(phase or current_phase())


def capabilities(phase: str | None = None) -> dict:
    return dict(CAPABILITIES.get(phase or current_phase(), CAPABILITIES["dormant"]))


def allows(action: str, phase: str | None = None) -> bool:
    """هل تسمح المرحلة الحالية بهذا السلوك **التلقائي**؟"""
    return bool(capabilities(phase).get(action, False))


def set_phase(phase: str, *, reason: str = "", by: str = "cli", acknowledge: bool = False) -> dict:
    """يضبط المرحلة. الترقية خطوة واحدة فقط؛ التراجع بلا قيود."""
    if phase not in PHASES:
        raise ValueError(f"مرحلة غير معروفة: {phase} — المتاح: {', '.join(PHASES)}")
    data = load()
    old = data["phase"]
    if phase == old:
        return {**data, "changed": False}
    if index(phase) > index(old) + 1:
        raise ValueError(
            f"لا يُسمح بالقفز من {old} إلى {phase} — خطوة واحدة في كل مرة "
            f"(التالية: {PHASES[index(old) + 1]}). الترقية التدريجية مقصودة."
        )
    if index(phase) > index(old) and acknowledge is False and phase == "primary":
        raise ValueError(f"المرحلة {phase} تحتاج توقيعًا بشريًا صريحًا: {ACK_ENV}={PRIMARY_ACK}")
    entry = {
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "from": old, "to": phase, "by": by,
        "reason": (reason or "")[:200],
        "direction": "advance" if index(phase) > index(old) else "rollback",
    }
    data.update({"phase": phase, "since": entry["at"], "changed_by": by,
                 "reason": entry["reason"], "changed": True})
    data["history"] = (data.get("history") or [])[-49:] + [entry]
    data.pop("corrupt", None)
    _write(data)
    log_event("rollout_phase_changed", **entry)
    return data


def rollback(to: str = "dormant", *, reason: str = "", by: str = "cli") -> dict:
    """تراجع فوري — متاح دائمًا، بلا شرط ولا دليل ولا انتظار."""
    if to not in PHASES:
        raise ValueError(f"مرحلة غير معروفة: {to}")
    return set_phase(to, reason=reason or "تراجع يدوي", by=by)


def kill(*, reason: str = "مفتاح إيقاف فوري", by: str = "cli") -> dict:
    """مفتاح إيقاف: يعيد كل شيء إلى `dormant` الآن. لا يمحو أي بيانات."""
    return rollback("dormant", reason=reason, by=by)


# --------------------------------------------------------------------- gate
def _read_audit(limit: int = 5000) -> list:
    target = os.path.join(data_dir(), "audit.jsonl")
    try:
        with open(target, encoding="utf-8") as handle:
            lines = handle.readlines()[-limit:]
    except (OSError, UnicodeDecodeError):
        return []
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _recent(events: list, names: set, phase_window: bool = True) -> list:
    """يقيّد الأحداث بفترة المرحلة الحالية إن أمكن (فلا تُحسب أدلة قديمة)."""
    since = load().get("since") or ""
    out = [event for event in events if event.get("event") in names]
    if phase_window and since:
        out = [event for event in out if str(event.get("ts") or "") >= since]
    return out


def gate(phase: str | None = None) -> dict:
    """هل تتحقق شروط الترقية إلى المرحلة المطلوبة؟ الأدلة من audit.jsonl."""
    target = phase or PHASES[min(index() + 1, len(PHASES) - 1)]
    if target == current_phase():
        return {"target": target, "current": current_phase(), "ok": True,
                "requirements": [], "detail": "لا ترقية مطلوبة — هذه هي المرحلة الحالية"}
    if index(target) < index():
        return {"target": target, "current": current_phase(), "ok": True,
                "requirements": [], "detail": "تراجع — مسموح دائمًا بلا شروط"}

    needs = dict(GATE_REQUIREMENTS.get(target, {}))
    for key, floor in GATE_FLOORS.items():
        if key in needs:
            needs[key] = max(needs[key], floor)
    events = _read_audit()
    ok_events = _recent(events, {"supabase_backup_done", "supabase_snapshot_pushed",
                                 "supabase_reconcile_done", "supabase_snapshot_pulled"})
    bad_events = _recent(events, {"supabase_backup_error", "supabase_snapshot_restore_blocked",
                                  "supabase_snapshot_pull_blocked"})
    # نعتمد **أحدث** مقارنة لا كل التاريخ: المقصود «هل الطبقة متطابقة الآن؟»،
    # لا «هل ظهر أي اختلاف خلال فترة الإعداد؟» — فالأخيرة تُعاقب على خطوات ترتيب
    # مشروعة وتمنع الترقية بلا سبب حقيقي.
    reconciles = _recent(events, {"supabase_reconcile_done"})
    latest_drift = int(reconciles[-1].get("drift") or 0) if reconciles else None

    checks = []
    runs_needed = int(needs.get("runs", 0))
    runs_ok = len(ok_events) >= runs_needed
    checks.append({
        "name": "تشغيلات ناجحة موثّقة", "ok": runs_ok,
        "detail": f"{len(ok_events)}/{runs_needed} (منذ {load().get('since') or 'البداية'})",
    })
    if "max_drift" in needs:
        drift_ok = latest_drift is not None and latest_drift <= int(needs["max_drift"])
        checks.append({
            "name": "آخر مقارنة بلا انحراف", "ok": drift_ok,
            "detail": ("لا توجد مقارنة موثّقة بعد — شغّل: python3 -m engine.rollout reconcile"
                       if latest_drift is None else
                       f"آخر مقارنة: انحراف {latest_drift} (المسموح {needs['max_drift']})"),
        })
    if "max_errors" in needs:
        errors_ok = len(bad_events) <= int(needs["max_errors"])
        checks.append({
            "name": "لا أخطاء في نافذة المرحلة", "ok": errors_ok,
            "detail": f"{len(bad_events)} خطأ (المسموح {needs['max_errors']})",
        })
    if needs.get("ack"):
        acked = (os.environ.get(ACK_ENV, "") or "").strip() == PRIMARY_ACK
        checks.append({
            "name": "توقيع بشري صريح للخطوة الأخيرة", "ok": acked,
            "detail": f"{ACK_ENV}={'مطابق' if acked else 'غير مضبوط أو غير مطابق'}",
        })
    passed = all(check["ok"] for check in checks)
    return {
        "target": target, "current": current_phase(), "ok": passed,
        "requirements": checks, "evidence": {"ok_events": len(ok_events), "errors": len(bad_events)},
        "detail": "اجتازت البوابة" if passed else "لم تجتز البوابة بعد — لا ترقية",
    }


def advance(*, reason: str = "", by: str = "cli", force: bool = False) -> dict:
    """ترقية خطوة واحدة — بشرط اجتياز البوابة. `force` لا يتجاوز بوابة المرحلة الأخيرة."""
    data = load()
    nxt = PHASES[min(index(data["phase"]) + 1, len(PHASES) - 1)]
    if nxt == data["phase"]:
        return {"changed": False, "phase": data["phase"], "detail": "وصلنا المرحلة الأخيرة"}
    report = gate(nxt)
    if not report["ok"] and not force:
        return {"changed": False, "phase": data["phase"], "blocked": True, "gate": report,
                "detail": f"البوابة نحو {nxt} لم تُجتَز — لم تتغير أي مرحلة"}
    if not report["ok"] and force:
        if nxt == "primary":
            return {"changed": False, "phase": data["phase"], "blocked": True, "gate": report,
                    "detail": "المرحلة الأخيرة لا تُفرض — تحتاج التوقيع والبوابة معًا"}
        log_event("rollout_gate_forced", target=nxt, by=by, reason=(reason or "")[:120])
    ack = nxt == "primary"
    result = set_phase(nxt, reason=reason or "ترقية", by=by, acknowledge=ack)
    result["gate"] = report
    return result


# ----------------------------------------------------------------- reconcile
def reconcile(*, client=None, state: dict | None = None) -> dict:
    """مقارنة المرآة في Supabase بالحالة المحلية — **قراءة فقط**، بلا أي كتابة.

    هذه أداة الإثبات الأساسية: بها نقول «الطبقة الجديدة تعمل فعلًا» لا «يبدو أنها
    تعمل». تُسجَّل نتيجتها في audit.jsonl ليعتمد عليها فحص البوابة.
    """
    from connectors import supabase_tasks
    report = supabase_tasks.reconcile(client=client, state=state)
    log_event("supabase_reconcile_done", drift=report.get("drift", 0),
              remote=report.get("remote_rows", 0), local=report.get("local_rows", 0))
    return report


def shadow_run(*, client=None) -> dict:
    """دورة ظلّ: قراءة ومقارنة فقط. ترفض العمل إن كانت المرحلة تسمح بالكتابة
    التلقائية (لتُستخدم في مكانها الدورة العادية)، وتعمل في `shadow` وما دونها."""
    if allows("automation_write"):
        return {"skipped": True, "detail": "المرحلة الحالية تسمح بالكتابة التلقائية — "
                                           "استخدم الدورة العادية بدل دورة الظلّ"}
    if not allows("automation_read"):
        return {"skipped": True, "detail": "المرحلة الحالية لا تسمح حتى بالقراءة التلقائية"}
    return reconcile(client=client)


# ------------------------------------------------------------------ reporting
def status() -> dict:
    data = load()
    phase = data["phase"]
    report = gate(PHASES[min(index(phase) + 1, len(PHASES) - 1)])
    return {
        "phase": phase, "label": PHASE_LABEL[phase], "since": data.get("since"),
        "reason": data.get("reason"), "corrupt": bool(data.get("corrupt")),
        "capabilities": capabilities(phase), "next": report["target"],
        "gate_ok": report["ok"], "gate": report, "history": (data.get("history") or [])[-5:],
    }


def render_status(data: dict) -> str:
    caps = data["capabilities"]
    on_off = lambda flag: "نعم" if flag else "لا"  # noqa: E731
    lines = [
        "🚦 مرحلة التشغيل التدريجي",
        f"المرحلة: {data['label']} (منذ {data.get('since') or '—'})",
        f"السبب: {data.get('reason') or '—'}",
        f"قراءة تلقائية: {on_off(caps['automation_read'])} · "
        f"كتابة تلقائية: {on_off(caps['automation_write'])}",
        "الأوامر اليدوية متاحة دائمًا في كل المراحل (لا يُمنع المالك من نسخة احتياطية).",
    ]
    if data.get("corrupt"):
        lines.append("⚠️ ملف المرحلة كان تالفًا — أُعيد الوضع الآمن.")
    if data["next"] != data["phase"]:
        lines.append("")
        lines.append(f"الخطوة التالية: {PHASE_LABEL[data['next']]} — "
                     f"البوابة: {'✅ مجتازة' if data['gate_ok'] else '⛔ لم تُجتَز'}")
        for check in data["gate"].get("requirements", []):
            lines.append(f"  {'✅' if check['ok'] else '⛔'} {check['name']}: {check['detail']}")
    else:
        lines.append("")
        lines.append("🎯 المرحلة النهائية — الطبقة الجديدة هي المسار الافتراضي لشأنها.")
    if data.get("history"):
        lines.append("")
        lines.append("آخر التغييرات:")
        for entry in reversed(data["history"]):
            lines.append(f"  {entry.get('at')} — {entry.get('from')} → {entry.get('to')} "
                         f"({entry.get('direction')}) {entry.get('reason') or ''}")
    lines.append("")
    lines.append("للتراجع فورًا: python3 -m engine.rollout kill  ·  أو من الجوال: /rollout_kill")
    return "\n".join(lines)


def plan() -> str:
    rows = [
        "🗺️ خطة التشغيل التدريجي",
        "",
        "| المرحلة | ما تُفعّله | ما يتغير في سير العمل القديم | التراجع |",
        "|---|---|---|---|",
        "| 0 dormant | لا شيء (لا شبكة) | لا شيء | — |",
        "| 1 shadow | قراءة ومقارنة آلية | لا شيء | kill |",
        "| 2 canary | كتابة بأمر بشري | لا شيء | kill |",
        "| 3 dual | الدفعة اليومية التلقائية | لا شيء (يعمل بالتوازي) | rollback --to canary |",
        "| 4 primary | النسخ التلقائي هو الافتراضي | يصبح الخطأ اليدوي اختياريًا (لا يُحذف) | rollback --to dual |",
        "",
        "⚠️ ما لن يُلغى في أي مرحلة:",
    ]
    rows += [f"  • {item}" for item in NEVER_RETIRED]
    rows += [
        "",
        "قاعدة الترقية: خطوة واحدة في كل مرة + اجتياز البوابة بالأدلة، والمرحلة الأخيرة",
        "تحتاج توقيعًا صريحًا. والتراجع مسموح دائمًا وفوري وبلا شروط.",
    ]
    return "\n".join(rows)


def simulate() -> str:
    """محاكاة: ماذا يعني كل احتمال انتقال؟ لا تُغيّر شيئًا إطلاقًا."""
    current = current_phase()
    lines = [f"🧪 محاكاة (لا تغيير فعلي) — المرحلة الحالية: {PHASE_LABEL[current]}", ""]
    for name in PHASES:
        caps = CAPABILITIES[name]
        mark = "◀ الحالية" if name == current else ""
        lines.append(f"{PHASE_LABEL[name]:<34} قراءة تلقائية: "
                     f"{'نعم' if caps['automation_read'] else 'لا'} · كتابة تلقائية: "
                     f"{'نعم' if caps['automation_write'] else 'لا'} {mark}")
    lines += [
        "",
        "أثر الترقية خطوةً واحدة على سير العمل القديم: **صفر** — القديم لا يتغير في أي مرحلة.",
        "أثر التراجع إلى dormant: تتوقف الأتمتة الجديدة فقط؛ لا تُحذف نسخة ولا صف،",
        "وكل الأوامر اليدوية تبقى تعمل.",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "status"

    def flag(name: str, default: str = "") -> str:
        if name in argv:
            idx = argv.index(name)
            if idx + 1 < len(argv):
                return argv[idx + 1]
        return default

    if command in ("status", "-h", "--help"):
        print(render_status(status()))
        return 0
    if command == "plan":
        print(plan())
        return 0
    if command == "simulate":
        print(simulate())
        return 0
    if command == "gate":
        print(json.dumps(gate(flag("--to") or None), ensure_ascii=False, indent=2))
        return 0
    if command == "reconcile":
        try:
            report = reconcile()
        except Exception as exc:  # noqa: BLE001
            print(f"❌ تعذرت المقارنة: {str(exc)[:200]}")
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("drift", 1) == 0 else 2
    if command in ("advance", "rollback", "kill"):
        try:
            if command == "advance":
                result = advance(reason=flag("--reason", "ترقية يدوية"), by="cli",
                                 force="--force" in argv)
            elif command == "rollback":
                result = rollback(flag("--to", "dormant"), reason=flag("--reason", "تراجع يدوي"))
            else:
                result = kill(reason=flag("--reason", "مفتاح إيقاف من الطرفية"))
        except ValueError as exc:
            print(f"❌ {exc}")
            return 2
        if result.get("blocked"):
            print("⛔ لم تتغير أي مرحلة — شروط غير مكتملة:")
            for check in result["gate"].get("requirements", []):
                print(f"  {'✅' if check['ok'] else '⛔'} {check['name']}: {check['detail']}")
            if command == "advance":
                print("   للإجبار (خطوة غير أخيرة): أضف --force")
            return 2
        if not result.get("changed", True):
            print(f"ℹ️ {result.get('detail') or 'لا تغيير'} — المرحلة: {PHASE_LABEL[result['phase']]}")
            return 0
        print(f"✅ {result['history'][-1]['from']} → {result['history'][-1]['to']} "
              f"({result['history'][-1]['direction']})")
        print(render_status(status()))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

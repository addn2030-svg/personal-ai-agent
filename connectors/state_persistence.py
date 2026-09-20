# -*- coding: utf-8 -*-
"""الحالة على مضيف **بلا قرص ثابت** (Render / Koyeb / أي استضافة مجانية).

المشكلة: الخطط المجانية لا تمنح قرصًا دائمًا. `data/state.json` يُفقد عند كل
إيقاف مؤقت أو إعادة نشر أو إعادة تشغيل — أي أن البوت «يفقد ذاكرته» باستمرار.
هذه الوحدة تجعل Supabase هو القرص:

    عند الإقلاع : آخر نسخة موقّعة تُنزَّل وتُستعاد إن كانت الحالة المحلية مفقودة
    أثناء العمل: كل تغيير يُدفع إلى Supabase (دفع تفاضلي — لا يُرسل ما لم يتغيّر)
    عند الإيقاف : دفع أخير قبل إنهاء العملية (Render يرسل SIGTERM قبل الإيقاف)

الراية الصريحة مطلوبة — لا شيء يعمل تلقائيًا بلا قرار من المالك:

| المتغير | الأثر |
|---|---|
| `AI_OS_STATE_RESTORE_ON_BOOT=1` | استعادة آخر نسخة عند الإقلاع إن فُقدت الحالة |
| `AI_OS_STATE_PERSIST=1` | دفع تفاضلي كل `AI_OS_STATE_PERSIST_SECONDS` (افتراضيًا 120) |
| `AI_OS_STATE_RESTORE_FORCE=1` | استعادة قسرية حتى لو وُجدت حالة محلية (للتصحيح اليدوي) |

الأمان أولًا:
- الاستعادة تتحقق من البصمة و`meta` **قبل** الكتابة (عبر `verify_row`) وتأخذ نسخة
  محلية قبل الاستبدال، فلا تفسد حالة قائمة بملف تالف.
- الدفع لا يعمل إلا بمفتاح سري + `SUPABASE_WRITE_ENABLED=1` (نفس حواجز الموصل).
- أي فشل شبكي **لا يُسقط العملية** — يُسجَّل ويُعاد في الدورة التالية.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from connectors import supabase_state  # noqa: E402
from connectors.supabase_client import SupabaseError, redact, truthy  # noqa: E402

STATE_FILE = ".state-persistence.json"
_LOCK = threading.Lock()
_THREAD = None


# ------------------------------------------------------------------- helpers
def enabled(name: str) -> bool:
    """راية بيئة — نفس دلالة `truthy` المستخدمة في بقية الموصلات (لا تعريف ثانٍ)."""
    return truthy(os.environ.get(name, ""))


def deflag(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def state_path() -> str:
    return supabase_state.state_path()


def _ledger_path() -> str:
    return os.path.join(supabase_state.data_dir(), STATE_FILE)


def _read_ledger() -> dict:
    """آخر ما دُفع فعليًا — لتفادي إعادة إرسال ما لم يتغيّر."""
    try:
        with open(_ledger_path(), encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_ledger(data: dict) -> None:
    target = _ledger_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temp = f"{target}.tmp-{os.getpid()}"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp, target)  # ذرّي: لا يبقى ملف نصف مكتوب
    except OSError:
        pass


def local_digest() -> str:
    """بصمة التمثيل القانوني للحالة الحالية (نفس بصمة النسخ — قابلة للمقارنة)."""
    state, _text = supabase_state.read_state()
    return supabase_state.payload_digest(state)


# ------------------------------------------------------------------ restore
def restore_on_boot(*, force: bool | None = None, client=None) -> dict:
    """يستعيد آخر نسخة عند الإقلاع إن كانت الحالة مفقودة (أو `force`)."""
    force = enabled("AI_OS_STATE_RESTORE_FORCE") if force is None else force
    path = state_path()
    report: dict = {"action": "skip", "restored": False, "detail": ""}

    if os.path.exists(path) and not force:
        report["detail"] = "الحالة المحلية موجودة — لا استعادة (المحلي يبقى المرجع)"
        return report

    try:
        row = supabase_state.fetch("latest", client=client)
    except SupabaseError as exc:
        if str(exc).startswith("لا توجد نسخة"):
            report["detail"] = "لا توجد نسخة في Supabase بعد — إقلاع أول نظيف"
            return report
        report.update({"action": "error", "detail": redact(str(exc))})
        supabase_state.log_event("state_restore_on_boot_failed", error=redact(str(exc))[:200])
        return report

    result = supabase_state.restore(row.get("id"), apply=True, client=client)
    if not result.get("applied"):
        report.update({"action": "refused",
                       "detail": " | ".join(result.get("problems") or ["فشل غير معروف"])})
        supabase_state.log_event("state_restore_on_boot_refused",
                                 snapshot_id=row.get("id"), problems=result.get("problems"))
        return report

    report.update({"action": "restored", "restored": True, "snapshot_id": row.get("id"),
                   "created_at": row.get("created_at"), "byte_size": row.get("byte_size"),
                   "detail": f"استُعيدت نسخة #{row.get('id')} من السحابة"})
    supabase_state.log_event("state_restored_on_boot", snapshot_id=row.get("id"))
    return report


# -------------------------------------------------------------------- push
def push_if_changed(*, client=None, reason: str = "تغيير حالة") -> dict:
    """يدفع الحالة إن اختلفت عن آخر نسخة دُفعت. لا يرسل شيئًا بلا تغيير."""
    with _LOCK:
        try:
            digest = local_digest()
        except (OSError, ValueError) as exc:
            return {"pushed": False, "detail": f"تعذر قراءة الحالة: {str(exc)[:120]}"}

        ledger = _read_ledger()
        if digest == ledger.get("sha256"):
            return {"pushed": False, "detail": "لا تغيير منذ آخر دفع", "sha256": digest}

        try:
            row = supabase_state.push(reason)
        except SupabaseError as exc:
            supabase_state.log_event("state_persist_failed", error=redact(str(exc))[:200])
            return {"pushed": False, "detail": redact(str(exc)), "sha256": digest}

        _write_ledger({"sha256": digest, "snapshot_id": row.get("id"),
                       "at": row.get("created_at") or "",
                       "pushed_at": time.time()})
        return {"pushed": True, "snapshot_id": row.get("id"), "sha256": digest,
                "byte_size": row.get("byte_size"), "detail": "دُفعت نسخة جديدة"}


def flush(*, client=None, reason: str = "إنهاء العملية") -> dict:
    """دفع أخير قبل الإيقاف — يتجاوز مقارنة البصمة لأن اللحظة حرجة.

    Render يرسل SIGTERM قبل إيقاف الحاوية، وهذه نافذة أخيرة لالتقاط أي تغيير لم
    تلحقه دورة الدفع. تفشل بهدوء إن لم يمكن الاتصال؛ لا نمنع الإنهاء أبدًا.
    """
    try:
        row = supabase_state.push(reason)
    except Exception as exc:  # noqa: BLE001 - الإنهاء لا يُعطَّل بسبب الشبكة
        return {"pushed": False, "detail": redact(str(exc))[:200]}
    try:
        _write_ledger({"sha256": supabase_state.payload_digest(
            supabase_state.read_state()[0]), "snapshot_id": row.get("id"),
            "pushed_at": time.time()})
    except Exception:  # noqa: BLE001
        pass
    return {"pushed": True, "snapshot_id": row.get("id")}


# -------------------------------------------------------------------- loop
def persist_loop(interval: int | None = None, *, client=None, stop_event=None) -> None:
    """دورة دفع تفاضلي في خيط خلفي — تتوقف عند `stop_event`."""
    interval = interval or deflag("AI_OS_STATE_PERSIST_SECONDS", 120)
    interval = max(30, int(interval))  # حد أدنى: لا نغرق Supabase بطلبات
    stop = stop_event or threading.Event()
    while not stop.wait(interval):
        try:
            push_if_changed(client=client)
        except Exception as exc:  # noqa: BLE001 - الدورة لا تسقط أبدًا
            supabase_state.log_event("state_persist_loop_error", error=str(exc)[:160])


def install_signal_flush() -> None:
    """يشغّل دفعًا أخيرًا عند SIGTERM/SIGINT ثم يُنهي العملية كما هو متوقع."""
    def handler(signum, frame):  # noqa: ARG001
        try:
            if enabled("AI_OS_STATE_PERSIST"):
                flush(reason=f"إنهاء بإشارة {signum}")
        finally:
            os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass  # خارج الخيط الرئيسي أو منصة لا تدعم الإشارة


# ------------------------------------------------------------------ install
def install(*, client=None) -> dict:
    """نقطة الدخول الواحدة من وقت التشغيل: استعادة إقلاع + إشارات + دورة دفع."""
    global _THREAD
    status: dict = {"restore": None, "persist": None, "flush_on_signal": False}

    if enabled("AI_OS_STATE_RESTORE_ON_BOOT"):
        status["restore"] = restore_on_boot(client=client)
        print(f"State restore on boot: {status['restore']['detail']}", flush=True)

    if enabled("AI_OS_STATE_PERSIST"):
        # لا نُشغّل دورة تدفع إلى العدم: بلا إعداد Supabase ستُفشل كل دورة وتغرق
        # سجلّ الاستضافة بلا فائدة. نُنبّه مرة واحدة بوضوح بدلًا من ذلك.
        from connectors.supabase_client import load_config
        cfg = load_config()
        if not cfg.configured:
            print("State persistence requested but Supabase is not configured — "
                  "check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", flush=True)
            status["persist"] = {"error": "supabase غير مضبوط"}
            return status
        if not cfg.can_write:
            print("State persistence requested but writing is disabled — "
                  "set SUPABASE_WRITE_ENABLED=1 with a secret key", flush=True)
            status["persist"] = {"error": "الكتابة مغلقة"}
            return status
        install_signal_flush()
        status["flush_on_signal"] = True
        if _THREAD is None or not _THREAD.is_alive():
            interval = max(30, deflag("AI_OS_STATE_PERSIST_SECONDS", 120))
            _THREAD = threading.Thread(target=persist_loop, kwargs={"interval": interval},
                                       name="state-persistence", daemon=True)
            _THREAD.start()
            status["persist"] = {"interval": interval}
            print(f"State persistence active: every {interval}s (differential push)", flush=True)
    return status


def main(argv=None) -> int:
    """أدوات يدوية: status · push · restore."""
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "status"
    if command == "status":
        try:
            digest = local_digest()
        except (OSError, ValueError) as exc:
            print(f"❌ لا حالة محلية: {str(exc)[:160]}")
            digest = None
        ledger = _read_ledger()
        print("💾 استمرارية الحالة")
        print(f"  مسار الحالة: {state_path()}")
        print(f"  موجودة محليًا: {'نعم' if os.path.exists(state_path()) else 'لا'}")
        print(f"  بصمة الحالة الحالية: {(digest or '—')[:16]}")
        print(f"  آخر دفع: {(ledger.get('sha256') or '—')[:16]} "
              f"(نسخة #{ledger.get('snapshot_id', '—')})")
        print(f"  مطابقة آخر دفع: {'نعم' if digest and digest == ledger.get('sha256') else 'لا'}")
        print(f"  استعادة عند الإقلاع: {'مفعّلة' if enabled('AI_OS_STATE_RESTORE_ON_BOOT') else 'مطفأة'}")
        print(f"  دفع تفاضلي: {'مفعّل' if enabled('AI_OS_STATE_PERSIST') else 'مطفأ'}")
        return 0
    if command == "push":
        try:
            print(json.dumps(push_if_changed(reason="دفع يدوي"), ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {redact(str(exc))}")
            return 2
        return 0
    if command == "restore":
        report = restore_on_boot(force=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("restored") or report["action"] == "skip" else 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""مهارات الوكيل المدير: حماية الإقلاع + البريف الصباحي المجدول.

مهارة 1 — استعادة الحالة عند الإقلاع (restore-on-boot):
  قبل تشغيل الخدمة: لو ملف state.json مفقود أو تالف ووجود نسخة سليمة
  في Supabase، تُستعاد تلقائيًا (مع نسخة وقائية قبلها). فشل الاستعادة
  لا يمنع الإقلاع — يُطبع التحذير فقط.

مهارة 2 — البريف الصباحي (المقاربة 1 المعتمدة، قرار 2026-11-02):
  كل يوم 06:30 بتوقيت الرياض: أولويتان (لا أكثر) من المهام المفتوحة،
  نص عادي بلا زخرفة، ثم سطر واحد للقرار المعلق إن وُجد.
  علامة يومية في /data تمنع التكرار، وسقف إعادة المحاولة 3.

تشغيل يدوي للاختبار:
  python3 -m connectors.morning_brief brief --force   # أرسل الآن (بلا جدولة)
  python3 -m connectors.morning_brief boot            # فحص/استعادة الإقلاع
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

DATA_DIR = Path(os.environ.get("AI_OS_DATA_DIR") or (BASE / "data"))
STATE_FILE = DATA_DIR / "state.json"
MARKER_FILE = DATA_DIR / "morning-brief-marker.json"
RIYADH = dt.timezone(dt.timedelta(hours=3))

MORNING_BRIEF_ENABLED = os.environ.get("MORNING_BRIEF_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
MORNING_BRIEF_HOUR = int(os.environ.get("MORNING_BRIEF_HOUR", "6"))
MORNING_BRIEF_MINUTE = int(os.environ.get("MORNING_BRIEF_MINUTE", "30"))
EVENING_BRIEF_ENABLED = os.environ.get("EVENING_BRIEF_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
EVENING_BRIEF_HOUR = int(os.environ.get("EVENING_BRIEF_HOUR", "19"))
EVENING_BRIEF_MINUTE = int(os.environ.get("EVENING_BRIEF_MINUTE", "45"))
EVENING_MARKER_FILE = DATA_DIR / "evening-brief-marker.json"
RESTORE_ON_BOOT = os.environ.get("SUPABASE_RESTORE_ON_BOOT", "1").strip().lower() in {"1", "true", "yes"}


def _log(event: str, **fields) -> None:
    """سجل تدقيق بسيط بنمط audit.jsonl — فشل السجل لا يعطّل شيئًا."""
    try:
        entry = {"ts": dt.datetime.now(RIYADH).isoformat(timespec="seconds"), "event": event}
        entry.update({k: v for k, v in fields.items() if v is not None})
        with open(DATA_DIR / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _state_healthy() -> bool:
    """هل ملف الحالة موجود وسليم البنية؟"""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return isinstance(data, dict)
    except Exception:
        return False


def ensure_boot_state() -> dict:
    """مهارة 1: استعادة تلقائية عند الإقلاع إن كانت الحالة مفقودة/تالفة.

    تعيد ملخصًا {action, ok, detail} — ولا ترفع استثناء أبدًا (fail-soft).
    """
    report = {"action": "none", "ok": True, "detail": "state.json سليم — لا استعادة مطلوبة"}
    if _state_healthy():
        return report
    if not RESTORE_ON_BOOT:
        report.update(ok=False, detail="state.json تالف/مفقود وRESTORE_ON_BOOT مغلق")
        print(f"boot-safety: {report['detail']}", flush=True)
        return report
    print("boot-safety: state.json مفقود/تالف — استعادة أحدث نسخة من Supabase", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "connectors.supabase_state", "restore", "--latest", "--apply"],
            capture_output=True, text=True, timeout=120, cwd=str(BASE),
        )
        ok = result.returncode == 0 and _state_healthy()
        report = {"action": "restore_latest", "ok": ok,
                  "detail": (result.stdout or result.stderr)[-300:]}
        _log("boot_state_restore", ok=ok)
        print(f"boot-safety: restore {'OK' if ok else 'FAILED'}: {report['detail'][:120]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        report = {"action": "restore_latest", "ok": False, "detail": str(exc)[:300]}
        _log("boot_state_restore", ok=False)
        print(f"boot-safety: restore error: {report['detail']}", flush=True)
    return report


def _open_tasks() -> list[dict]:
    """المهام المفتوحة من مصدر الحقيقة (مرتبة أولوية ثم موعدًا)."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict)
             and t.get("الحالة") not in {"منجزة", "ملغاة", "مكتمل"}]
    order = {"عالية": 0, "عالي": 0, "high": 0, "متوسطة": 1, "متوسط": 1, "medium": 1}
    tasks.sort(key=lambda t: (
        order.get(str(t.get("الأولوية") or t.get("priority") or "").strip().lower(), 2),
        str(t.get("تاريخ الاستحقاق") or t.get("due_date") or "9999"),
    ))
    return tasks


def _top_priorities(limit: int = 2) -> list[dict]:
    return _open_tasks()[:limit]


def _today_done() -> list[dict]:
    """ما أُنجز اليوم تحديدًا (للملخص المسائي)."""
    today = dt.datetime.now(RIYADH).date().isoformat()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for t in (data.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        done = str(t.get("تاريخ الإتمام") or t.get("completed_at")
                    or t.get("آخر تحديث") or t.get("last_update") or "")
        if t.get("الحالة") in {"منجزة", "مكتمل"} and done[:10] == today:
            out.append(t)
    return out


def build_evening_text() -> str:
    """ملخص اليوم + التحضير لغدٍ: ما أُنجز، ما المعلّق، أولويتا الغد، قرار معلق.

    وظيفته التحضير المسائي — يصلك في ذروة استخدامك (19-20) قبل نهاية اليوم.
    """
    now = dt.datetime.now(RIYADH)
    done = _today_done()
    open_tasks = _open_tasks()
    tomorrow_due = [t for t in open_tasks
                    if str(t.get("تاريخ الاستحقاق") or t.get("due_date") or "")[:10]
                    == (now.date() + dt.timedelta(days=1)).isoformat()]
    tops = tomorrow_due[:2] or open_tasks[:2]

    lines = [f"ملخص اليوم — {now.strftime('%A %Y-%m-%d')}"]
    if done:
        lines.append(f"أنجزت اليوم: {len(done)} — "
                     + "، ".join(str(t.get("العنوان") or t.get("title") or "")[:40]
                                 for t in done[:3]))
    else:
        lines.append("لا مهام مُنجزة مسجلة اليوم.")
    lines.append(f"المعلّق: {len(open_tasks)} مهمة مفتوحة"
                 + (f" — المتأخرة منها: {sum(1 for t in open_tasks if str(t.get('سبب التعثر') or '').strip())}" )
                 if open_tasks else "لا معلّق — نظيف.")
    if tops:
        lines.append("تحضير الغد — ابدأ بهذين:")
        for i, t in enumerate(tops, 1):
            lines.append(f"{i}) {str(t.get('العنوان') or t.get('title') or 'بلا عنوان')[:90]}")
    else:
        lines.append("غدك نظيف — لا مهام مستحقة.")
    lines.append(_pending_decision_line().strip() or "")
    return "\n".join(l for l in lines if l.strip())


def _pending_decision_line() -> str:
    """سطر واحد للقرار المعلق إن وُجد (لا قوائم طويلة صباحًا)."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for d in (data.get("decision_requests") or []):
        if isinstance(d, dict) and str(d.get("status", "")).upper() == "PENDING":
            return f"\nقرار معلق: {str(d.get('title', d.get('id', '')))[:80]} — أرسل /decisions"
    return ""


def build_brief_text() -> str:
    """نص البريف الصباحي: نص عادي، أولويتان، لا زخرفة ولا قوائم طويلة."""
    now = dt.datetime.now(RIYADH)
    tops = _top_priorities(2)
    if not tops:
        body = "لا مهام مفتوحة مسجلة في الحالة اليوم."
    else:
        lines = []
        for i, t in enumerate(tops, 1):
            title = str(t.get("العنوان") or t.get("title") or "بلا عنوان")[:90]
            lines.append(f"{i}) {title}")
        body = "\n".join(lines)
    return (f"صباح الخير عبدالرحمن — {now.strftime('%A %Y-%m-%d')}\n"
            f"أولوياتك اليوم:\n{body}"
            + _pending_decision_line())


def _marker_date(marker: Path) -> str:
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("date", "")
    except Exception:
        return ""


def _mark_sent(marker: Path, today: str) -> None:
    try:
        marker.write_text(json.dumps({"date": today}), encoding="utf-8")
    except Exception:
        pass


def maybe_send_morning_brief(bot_send=None) -> dict:
    """مهارة 2: أرسل البريف إن حان وقته ولم يُرسل اليوم. يعيد {sent, reason}."""
    now = dt.datetime.now(RIYADH)
    today = now.date().isoformat()
    due = (now.hour, now.minute) >= (MORNING_BRIEF_HOUR, MORNING_BRIEF_MINUTE)
    if not due:
        return {"sent": False, "reason": f"لم يحن الوقت (الآن {now.strftime('%H:%M')} ريال)"}
    if _marker_date(MARKER_FILE) == today:
        return {"sent": False, "reason": "أُرسل اليوم بالفعل"}

    text = build_brief_text()
    return _send_once(text, MARKER_FILE, today, "morning_brief_sent", bot_send)


def maybe_send_evening_brief(bot_send=None, force: bool = False) -> dict:
    """مهارة 2ب: ملخص اليوم + تحضير الغد في ذروة استخدامك المسائية."""
    if not EVENING_BRIEF_ENABLED:
        return {"sent": False, "reason": "المسائي مغلق (EVENING_BRIEF_ENABLED)"}
    now = dt.datetime.now(RIYADH)
    today = now.date().isoformat()
    if not force:
        due = (now.hour, now.minute) >= (EVENING_BRIEF_HOUR, EVENING_BRIEF_MINUTE)
        if not due:
            return {"sent": False, "reason": f"لم يحن وقت المسائي (الآن {now.strftime('%H:%M')})"}
        if _marker_date(EVENING_MARKER_FILE) == today:
            return {"sent": False, "reason": "أُرسل المسائي اليوم بالفعل"}
    return _send_once(build_evening_text(), EVENING_MARKER_FILE, today,
                      "evening_brief_sent", bot_send)


def _send_once(text: str, marker: Path, today: str, event: str, bot_send=None) -> dict:
    if bot_send is None:
        from connectors import telegram_bot_legacy as legacy
        owner = legacy._owner_id()
        if not owner:
            return {"sent": False, "reason": "لا معرف مالك محفوظ"}
        bot_send = lambda t: legacy.send(int(owner), t)  # noqa: E731
    try:
        bot_send(text)
        _mark_sent(marker, today)
        _log(event, chars=len(text))
        print(f"{event}: sent ({len(text)} chars)", flush=True)
        return {"sent": True, "reason": "أُرسل"}
    except Exception as exc:  # noqa: BLE001
        _log(event + "_failed", detail=str(exc)[:200])
        print(f"{event}: send failed: {str(exc)[:150]}", flush=True)
        return {"sent": False, "reason": f"فشل الإرسال: {str(exc)[:120]}"}


def start_scheduler(bot_send=None) -> threading.Thread:
    """خيط جدولة خفيف: صباحي 06:30 + مسائي 19:45، بفحص كل 10 دقائق."""
    state = {"m_attempts": 0, "e_attempts": 0}

    def loop():
        while True:
            try:
                now = dt.datetime.now(RIYADH)
                today = now.date().isoformat()
                # صباحي
                if MORNING_BRIEF_ENABLED and state["m_attempts"] < 3:
                    r = maybe_send_morning_brief(bot_send)
                    if r["sent"] or "أُرسل اليوم" in r["reason"]:
                        state["m_attempts"] = 3
                    elif "لم يحن" not in r["reason"]:
                        state["m_attempts"] += 1
                # مسائي
                if EVENING_BRIEF_ENABLED and state["e_attempts"] < 3:
                    r = maybe_send_evening_brief(bot_send)
                    if r["sent"] or "أُرسل المسائي" in r["reason"]:
                        state["e_attempts"] = 3
                    elif "لم يحن" not in r["reason"] and "مغلق" not in r["reason"]:
                        state["e_attempts"] += 1
                # تصفير عدادات اليوم الجديد
                if now.hour < MORNING_BRIEF_HOUR:
                    state["m_attempts"] = 0
                    state["e_attempts"] = 0
            except Exception as exc:  # noqa: BLE001
                print(f"brief scheduler error: {str(exc)[:150]}", flush=True)
            time.sleep(600)
    th = threading.Thread(target=loop, daemon=True, name="daily-briefs")
    th.start()
    return th


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="morning_brief")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("boot", help="فحص/استعادة حالة الإقلاع")
    b = sub.add_parser("brief", help="بناء/إرسال البريف الصباحي")
    b.add_argument("--text", action="store_true", help="اطبع النص فقط بلا إرسال")
    b.add_argument("--force", action="store_true", help="أرسل الآن متجاهلًا الوقت والعلامة")
    e = sub.add_parser("evening", help="ملخص اليوم + تحضير الغد")
    e.add_argument("--text", action="store_true", help="اطبع النص فقط بلا إرسال")
    e.add_argument("--force", action="store_true", help="أرسل الآن متجاهلًا الوقت والعلامة")
    args = parser.parse_args(argv)
    if args.cmd == "boot":
        report = ensure_boot_state()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    if args.cmd == "evening":
        if args.text:
            print(build_evening_text())
            return 0
        result = maybe_send_evening_brief(force=args.force)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["sent"] else 1
    if args.text:
        print(build_brief_text())
        return 0
    if args.force:
        _mark_sent(MARKER_FILE, "")  # تجاوز العلامة ثم أرسل الآن مهما كان الوقت
    result = maybe_send_morning_brief()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["sent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
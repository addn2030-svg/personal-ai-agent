# -*- coding: utf-8 -*-
"""
أهداف البحث الدورية (v1.2) — سجل GOAL واحد يتبدّل، والأدوات ثابتة.

الفكرة المأخوذة من نمط «المساعد البحثي»: وكيل بمسار واحد، لا تغيّر منه سوى الهدف.
الفرق الجوهري عن النسخة السهلة في الشروحات: **هذا المحرك لا يتصفّح ولا يشبِك**.
`connectors/task_delegation.py` يقرّر أن النماذج استدلال فقط ولا تُمنح أذونات
متصفح/Drive/بريد، وأي أثر خارجي يبقى خلف بوابات الاعتماد — فنحن نلتزم بذلك:

    add  →  هيكل كبسولة فارغ بميزانية توكن (أنت من يملؤه من جلسة بحث خارجية)
    attach → يلحق مصدرًا (نص بحث جاهز) بالمجلد research_capsules/inbox/
    run_due → يروّج المُلحَق إلى كبسولة READY بعد فحص الميزانية، ويولّد الهياكل المستحقة

كل وظيفة هنا محلية الحتمية: تكتب ملفات وتحدّث الحالة، ولا تخرج إلى الشبكة.

الأوامر:
  python3 engine/research_goals.py list
  python3 engine/research_goals.py add "أفكار محتوى من أسئلة الجمهور" --cadence weekly \
      --weekday 0 --at 05:40 --mode deep
  python3 engine/research_goals.py attach RG-001 /tmp/research.md
  python3 engine/research_goals.py run --due          # ما ينفّذه التوقيت فعلًا
  python3 engine/research_goals.py run --all          # بلا انتظار الدورة
  python3 engine/research_goals.py due
  python3 engine/research_goals.py enable RG-001 | disable RG-001 | remove RG-001
  python3 engine/research_goals.py text               # جدول يُدفع في رسالة
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event  # noqa: E402

SECTION = "research_goals"
# المسارات دوالٌ لا ثوابت: الاختبارات تحقن CAPSULE_DIR المؤقت، والثوابت
# الملتقطة وقت الاستيراد كانت ستكتب في شجرة المستودع الحقيقية أثناء الجري.
CAPSULE_DIR = os.path.join(BASE, "research_capsules")


def _capsule_dir():
    return CAPSULE_DIR


def _inbox_dir():
    return os.path.join(CAPSULE_DIR, "inbox")


def _rel(path):
    """مسار معروض: نسبي داخل المستودع، ومطلق خارجه — بلا ../../../ عندها."""
    try:
        rel = os.path.relpath(path, BASE)
    except ValueError:
        return os.path.abspath(path)
    return os.path.abspath(path) if rel.startswith("..") else rel

# قالب research_capsules/README.md — 500–1,200 توكن. التقدير 4.2 حرف/توكن متحفظ
# عمدًا: نصّ عربي/إنجليزي مختلط، والأفضل رفض الطويل على حشو سياق المدير.
TOKEN_BUDGET_MAX = 1200
CHARS_PER_TOKEN = 4.2
CADENCES = ("daily", "weekly", "manual")
AR_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
SECTIONS = ("KEY FINDINGS", "EVIDENCE / SOURCE REFS", "OPTIONS",
            "RISKS / CONTRADICTIONS", "OPEN QUESTIONS", "RECOMMENDED TEST")


def now():
    return dt.datetime.now(dt.timezone.utc).astimezone()


# ---------------------------------------------------------------- المفكرة
def _hhmm(raw, default="05:40"):
    raw = str(raw or "").strip()
    m = re.match(r"^(\d{1,2})\s*:\s*(\d{1,2})$", raw)
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return default
    return f"{h:02d}:{mi:02d}"


def read_goals(store=None):
    store = store or Store()
    return [dict(g) for g in store.rows_all().get(SECTION, [])]


def _mutate(store, fn, mutator, **details):
    """fn(rows) → (changed, result). يعيد (changed, result) نفسه.

    ملاحظة بنائية: Store.transaction يعيد result فقط ولا يخبرنا هل جرت كتابة،
    لذلك نخرج بـ changed من داخل دالة التعديل عبر holder مشترك.
    """
    holder = {}

    def change(S):
        # نسخة قابلة للتعديل — ويجب إعادتها إلى المقطع، وإلا تُحفظ حالة فارغة
        rows = [dict(g) for g in S.get(SECTION, [])]
        changed, result = fn(rows)
        if changed:
            S[SECTION] = rows
        holder["changed"] = bool(changed)
        return bool(changed), result

    result = store.transaction(change, f"research_goals_{mutator}", **details)
    return holder.get("changed", False), result


def _next_id(rows):
    n = 0
    for r in rows:
        m = re.match(r"^RG-(\d+)$", str(r.get("goal_id") or ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"RG-{n + 1:03d}"


def add_goal(goal, cadence="weekly", weekday=0, at="05:40", mode="deep",
             capsule="", store=None, ref=None):
    """يسجّل هدفًا ويعيد (goal, ملف الهيكل إن أُنشئ). idempotent بنص الهدف."""
    goal = " ".join(str(goal or "").split())
    if not goal:
        raise ValueError("الهدف نص فارغ")
    if cadence not in CADENCES:
        raise ValueError(f"cadence يجب أن تكون واحدة من {CADENCES}")
    if mode not in ("lean", "standard", "deep"):
        raise ValueError("mode: lean | standard | deep")
    row = {"goal_id": None, "goal": goal, "cadence": cadence,
           "weekday": int(weekday) % 7, "at": _hhmm(at), "mode": mode,
           "enabled": True, "capsule": " ".join(str(capsule or "").split()),
           "added": now().date().isoformat(), "source": "manual:research_goals.py",
           "status": None, "last_run": None, "cycle_key": None, "path": None,
           "goal_hash": hashlib.sha256(goal.encode("utf-8")).hexdigest()[:12]}

    def fn(rows):
        hit = next((r for r in rows if r.get("goal_hash") == row["goal_hash"]), None)
        if hit:
            return False, (hit, None)
        row["goal_id"] = _next_id(rows)
        rows.append(row)
        path = write_skeleton(row, ref)
        row["path"] = path
        return True, (row, path)

    changed, result = _mutate(store or Store(), fn, "add", goal=row["goal_hash"])
    if changed:
        row, path = result
    else:
        row, path = (result[0] if isinstance(result, tuple) else row), None
    return changed, row, path


def toggle(goal_id, enabled=True, store=None):
    def fn(rows):
        hit = next((r for r in rows if str(r.get("goal_id")) == str(goal_id)), None)
        if not hit:
            return True, "not_found"
        hit["enabled"] = bool(enabled)
        return True, hit
    _c, hit = _mutate(store or Store(), fn, "toggle", goal_id=goal_id)
    if hit is None or hit == "not_found":
        return False, None
    return True, hit


def remove_goal(goal_id, store=None):
    def fn(rows):
        # لا «rows = ...» هنا: إعادة إسناد الاسم محليًّا تترك المقارنة في السطر
        # التالي تقارن القائمة القديمة بنفسها، فلا يُحذف شيء أبدًا.
        before = len(rows)
        rows[:] = [r for r in rows if str(r.get("goal_id")) != str(goal_id)]
        if len(rows) == before:
            return True, "not_found"
        return True, before - len(rows)
    _c, n = _mutate(store or Store(), fn, "remove", goal_id=goal_id)
    if n is None or n == "not_found":
        return False, 0
    return True, n


def attach(goal_id, src_path, store=None):
    """يلحق نص بحث جاهز (من جلسة خارجية) بالهدف — لا شبكة هنا ولا نسخة ثانية."""
    src = os.path.abspath(src_path or "")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"الملف غير موجود: {src}")
    if os.path.getsize(src) > 400_000:
        raise ValueError("المصدر أكبر من 400KB — اقتطع منه قبل الإلحاق")
    os.makedirs(_inbox_dir(), exist_ok=True)
    with open(src, "rb") as f:
        blob = f.read()
    digest = hashlib.sha256(blob).hexdigest()[:12]
    dest = os.path.join(_inbox_dir(), f"{goal_id}-{digest}.md")
    if os.path.abspath(src) != dest:
        with open(dest, "wb") as f:
            f.write(blob)

    def fn(rows):
        hit = next((r for r in rows if str(r.get("goal_id")) == str(goal_id)), None)
        if not hit:
            return True, "not_found"
        hit["inbox"] = _rel(dest)
        hit["inbox_sha"] = digest
        return True, hit
    changed, hit = _mutate(store or Store(), fn, "attach", goal_id=goal_id)
    if hit in (None, "not_found"):
        return False, None, _rel(dest)
    return True, hit, _rel(dest)


# ---------------------------------------------------------------- الكبسولات
def capsule_path(goal_id, ref=None):
    day = (ref or now()).date().isoformat()
    return os.path.join(_capsule_dir(), f"{goal_id}-{day}.md")


def skeleton_text(row, ref=None):
    t = ref or now()
    head = (f"TITLE: {row['goal']}\n"
            f"OBJECTIVE: {row['goal']}\n"
            f"DATE: {t.date().isoformat()}\n"
            f"GOAL_ID: {row['goal_id']} · MODE: {row.get('mode', 'deep')} · "
            f"CADENCE: {row.get('cadence')}\n"
            f"SOURCE: NEEDED — املأ الأقسام من جلسة بحث خارجية، أو: "
            f"python3 engine/research_goals.py attach {row['goal_id']} <ملف>\n")
    body = []
    for s in SECTIONS:
        body.append(f"{s}:\n-")
    return head + "\n" + "\n\n".join(body) + "\n"


def write_skeleton(row, ref=None):
    path = capsule_path(row["goal_id"], ref)
    os.makedirs(_capsule_dir(), exist_ok=True)
    body = skeleton_text(row, ref)
    if os.path.exists(path):          # لا نكتب فوق كبسولة جاهزة/محرّرة
        return _rel(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return _rel(path)


def _estimate_tokens(text):
    return int(len(text or "") / CHARS_PER_TOKEN)


def promote(row, ref=None):
    """ينقل نص inbox إلى كبسولة READY مع فحص الميزانية وقفل البصمة."""
    src = row.get("inbox")
    if not src:
        return False, "no_inbox", None
    abs_src = src if os.path.isabs(src) else os.path.join(BASE, src)
    if not os.path.isabs(src) and not abs_src.startswith(BASE):
        return False, "inbox_outside_repo", None
    if not os.path.isfile(abs_src):
        return False, "inbox_missing", None
    with open(abs_src, encoding="utf-8", errors="ignore") as f:
        body = f.read().strip()
    if not body:
        return False, "inbox_empty", None
    est = _estimate_tokens(body)
    path = capsule_path(row["goal_id"], ref)
    os.makedirs(_capsule_dir(), exist_ok=True)
    header = (f"<!-- research-goal {row['goal_id']} · {row['goal']} -->\n"
              f"<!-- attached {row.get('inbox_sha')} · promoted {(ref or now()).isoformat(timespec='seconds')} -->\n\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
    status = "READY" if est <= TOKEN_BUDGET_MAX else "READY_TRIM_ME"
    rel = _rel(path)
    if status == "READY_TRIM_ME":
        log_event("research_capsule_over_budget", goal_id=row["goal_id"], tokens=est,
                  budget=TOKEN_BUDGET_MAX)
    return True, status, rel


# ---------------------------------------------------------------- الاستحقاق
def cycle_key(row, ref):
    cad = row.get("cadence", "weekly")
    if cad == "daily":
        return ref.date().isoformat()
    if cad == "manual":
        return "manual"
    iso = ref.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def due_goals(ref=None, store=None, rows=None):
    """(المستحقة، المؤجَّلة مع السبب) — منطق مستقل عن دورية وظيفة التوقيت."""
    t = ref or now()
    rows = read_goals(store) if rows is None else rows
    due, held = [], []
    for row in rows:
        if not row.get("enabled", True):
            held.append((row, "معطّل"))
            continue
        key = cycle_key(row, t)
        # SKELETON لا يُقفل الدورة: الكبسولة الفارغة غير مُنجَزة، فالهدف يبقى
        # مستحقًا في كل جري حتى يُرفق مصدر ويُروَّج (READY). هذا مقصود — دورة
        # البحث «حتى الامتلاء» لا «مرة واحدة وتُنسى».
        if row.get("cycle_key") == key and row.get("status") not in (None, "SKELETON"):
            held.append((row, "نُفِّذ في هذه الدورة"))
            continue
        job_at = _hhmm(row.get("at"))
        if row.get("cadence") == "weekly" and t.weekday() != int(row.get("weekday", 0)) % 7:
            held.append((row, f"ليس {AR_DAYS[int(row.get('weekday', 0)) % 7]}"))
            continue
        if t.time() < dt.time(*[int(x) for x in job_at.split(":")]):
            held.append((row, f"لم يحن {job_at} بعد"))
            continue
        due.append(row)
    return due, held


def run_due(ref=None, store=None, force=False, verbose=True, record=True):
    """يشغّل ما يستحق: يروّج المُلحَق، ثم يولّد هياكل الباقين. يعيد (ok, detail)."""
    t = ref or now()
    store = store or Store()
    rows = read_goals(store)
    if force:
        due = [r for r in rows if r.get("enabled", True)]
        held = [(r, "وضع --all") for r in rows if not r.get("enabled", True)]
    else:
        due, held = due_goals(t, store=store, rows=rows)
    detail = {"due": len(due), "capsules": [], "errors": [], "deferred": len(held)}
    if not due:
        return True, detail
    results = {}
    for row in due:
        try:
            if row.get("inbox"):
                ok, status, rel = promote(row, t)
                if not ok and status in ("inbox_missing", "inbox_empty"):
                    status, rel = "SKELETON", write_skeleton(row, t)
            else:
                status, rel = "SKELETON", write_skeleton(row, t)
            est = None
            if rel and status.startswith("READY"):
                try:
                    with open(os.path.join(BASE, rel), encoding="utf-8") as f:
                        est = _estimate_tokens(f.read())
                except OSError:
                    est = None
            detail["capsules"].append({"goal_id": row["goal_id"], "status": status,
                                       "path": rel, "tokens": est})
            results[row["goal_id"]] = {"status": status, "path": rel,
                                       "cycle_key": cycle_key(row, t)}
        except Exception as exc:  # noqa: BLE001
            detail["errors"].append(f"{row['goal_id']}: {str(exc)[:160]}")
            results[row["goal_id"]] = {"status": "error", "error": str(exc)[:160],
                                       "cycle_key": cycle_key(row, t)}
    if verbose:
        for c in detail["capsules"]:
            print(f"🔬 {c['goal_id']} → {c['status']}: {c['path']}"
                  + (f" (~{c['tokens']} توكن)" if c.get("tokens") else ""))
    if record and results:
        def fn(existing):
            by_id = {str(r.get("goal_id")): r for r in existing}
            for gid, info in results.items():
                r = by_id.get(gid)
                if r is None:
                    continue
                r["status"] = info["status"]
                r["last_run"] = t.isoformat(timespec="seconds")
                r["cycle_key"] = info["cycle_key"]
                r["path"] = info.get("path") or r.get("path")
            return True, len(results)
        _mutate(store, fn, "run", n=len(results))
    ok = not detail["errors"]
    return ok, detail


# ---------------------------------------------------------------- العرض
def goals_text(store=None, ref=None):
    rows = read_goals(store)
    if not rows:
        return ("🔬 لا أهداف بحث مسجّلة.\n"
                "أضف واحدًا: python3 engine/research_goals.py add \"<الهدف>\" "
                "--cadence weekly --weekday 0 --at 05:40")
    due, _held = due_goals(ref, store=store, rows=rows)
    due_ids = {str(r.get("goal_id")) for r in due}
    lines = [f"🔬 أهداف البحث — {len(rows)} مسجّلة · المستحق الآن {len(due)}",
             ""]
    for r in rows:
        cad = r.get("cadence")
        when = {"daily": f"يومي {r.get('at')}",
                "weekly": f"{AR_DAYS[int(r.get('weekday', 0)) % 7]} {r.get('at')}",
                "manual": "يدوي"}.get(cad, str(cad))
        mark = "🟢" if str(r.get("goal_id")) in due_ids else ("⚪" if r.get("enabled", True) else "⏸️")
        state = r.get("status") or "لم تُشغَّل"
        lines.append(f"{mark} {r['goal_id']} · {when} · {r.get('mode')} · {state}")
        lines.append(f"   {r.get('goal')}")
    lines += ["", "المحرك لا يتصفّح: املأ الهيكل من جلسة بحث خارجية، "
                  "أو ألحق نصًّا وسيقوم التوقيت بترويجه."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="أهداف البحث الدورية — بلا شبكة، بلا إرسال")
    ap.add_argument("cmd", choices=["list", "add", "attach", "run", "due", "enable",
                                    "disable", "remove", "text"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("arg2", nargs="?")
    ap.add_argument("--cadence", default="weekly", choices=CADENCES)
    ap.add_argument("--weekday", type=int, default=0)
    ap.add_argument("--at", default="05:40")
    ap.add_argument("--mode", default="deep", choices=["lean", "standard", "deep"])
    ap.add_argument("--capsule", default="")
    ap.add_argument("--all", dest="all_", action="store_true", help="شغّل الكل بلا انتظار دورة")
    ap.add_argument("--no-record", action="store_true", help="لا تكتب أثر التشغيل في الحالة")
    args = ap.parse_args(argv)
    store = Store()

    if args.cmd == "list":
        rows = read_goals(store)
        if not rows:
            print("لا أهداف بعد."); return 0
        for r in rows:
            print(f"{r['goal_id']}  {'⏸️' if not r.get('enabled', True) else '▶️'}  "
                  f"{r.get('cadence')} {r.get('at')}  {r.get('mode')}  "
                  f"{r.get('status') or '-'}  · {r.get('goal')[:60]}")
        return 0
    if args.cmd == "text":
        print(goals_text(store)); return 0
    if args.cmd == "due":
        due, held = due_goals(store=store)
        print(f"مستحق: {len(due)} · مؤجَّل: {len(held)}")
        for r in due:
            print(f"  🟢 {r['goal_id']} {r.get('goal')[:60]}")
        for r, why in held:
            print(f"  ⏳ {r['goal_id']} — {why}")
        return 0
    if args.cmd == "add":
        if not args.arg:
            print("❌ الصيغة: research_goals.py add \"<الهدف>\" [--cadence …] [--at HH:MM]"); return 2
        changed, row, path = add_goal(args.arg, args.cadence, args.weekday, args.at,
                                      args.mode, args.capsule, store)
        if not changed:
            print(f"ℹ️ الهدف مسجّل مسبقًا: {row['goal_id']} (لم يُكرَّر)")
        else:
            print(f"✅ {row['goal_id']} · {row['cadence']} {row['at']} · {row['mode']}")
            print(f"   الهيكل: {path}")
        return 0
    if args.cmd == "attach":
        if not args.arg or not args.arg2:
            print("❌ الصيغة: research_goals.py attach RG-001 <ملف>"); return 2
        changed, hit, dest = attach(args.arg, args.arg2, store)
        if not changed:
            print(f"❌ لا هدف بالمعرف {args.arg}"); return 2
        print(f"📎 أُلحق المصدر: {dest}")
        print(f"   سيُروَّج إلى كبسولة READY في دورة التوقيت القادمة — أو الآن: "
              f"python3 engine/research_goals.py run")
        return 0
    if args.cmd in ("enable", "disable"):
        changed, hit = toggle(args.arg, args.cmd == "enable", store)
        print(f"{'✅' if changed else '❌'} {args.arg} → "
              f"{'مفعّل' if hit and hit.get('enabled') else 'معطّل' if hit else 'لا يوجد'}")
        return 0 if changed else 2
    if args.cmd == "remove":
        changed, n = remove_goal(args.arg, store)
        print(f"{'✅ أُزيل' if changed else '❌ لا يوجد'} {args.arg}")
        return 0 if changed else 2
    if args.cmd == "run":
        ok, detail = run_due(store=store, force=args.all_, record=not args.no_record)
        print(f"{'✅' if ok else '❌'} مستحق {detail['due']} · كبسولات "
              f"{len(detail['capsules'])} · مؤجَّل {detail['deferred']} · "
              f"أخطاء {len(detail['errors'])}")
        for e in detail["errors"]:
            print(f"   ⚠️ {e}")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

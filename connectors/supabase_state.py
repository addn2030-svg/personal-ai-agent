# -*- coding: utf-8 -*-
"""State snapshots → Supabase — نسخة احتياطية متينة خارج الخادم.

السبب: ملف `data/state.json` هو مصدر الحقيقة، لكنه يعيش على قرص Railway وحده.
حجم Railway يُفقد عند حذف الخدمة، والنسخ الدوارة المحلية (`data/backups/`) تقع على
نفس القرص، و`docs/agent3-p0-adjudication.md` يسجّل هذا كخطر متبقٍّ مقبول مؤقتًا.
هذه الوحدة تغلق ذلك الخطر: تدفع نسخة كاملة موقّعة بـsha256 إلى جدول Supabase
`state_snapshots`، ويمكن استرجاعها لاحقًا بتحقّق كامل.

قواعد السلامة:
- **الدفع** يحتاج `SUPABASE_SERVICE_ROLE_KEY` + `SUPABASE_WRITE_ENABLED=1`.
- **الاسترجاع لا يكتب شيئًا افتراضيًا**: بدون `--apply` يطبع تقريرًا فقط.
- **قبل أي كتابة** تُحفظ الحالة الحالية في `data/backups/state-pre-restore-*.json`
  (نسخ لا نقل)، ثم يُكتب الملف الجديد ذرّيًا عبر `os.replace`.
- **التحقق أولًا**: sha256 للحمولة + وجود الأقسام الأساسية + `meta`.
- كل عملية تُسجَّل في `audit.jsonl` (`supabase_snapshot_pushed` / `_restored`).

أمثلة:
  python3 -m connectors.supabase_state push --reason "قبل ترحيل Railway"
  python3 -m connectors.supabase_state list --limit 10
  python3 -m connectors.supabase_state show --id 12
  python3 -m connectors.supabase_state restore --id 12            # معاينة فقط
  python3 -m connectors.supabase_state restore --id 12 --apply    # كتابة فعلية
  python3 -m connectors.supabase_state prune --keep 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from connectors.supabase_client import (  # noqa: E402
    SupabaseClient, SupabaseError, load_config, redact,
)

REQUIRED_SECTIONS = ("meta", "tasks", "projects", "decisions", "waiting_for", "action_queue")


def data_dir() -> str:
    return os.environ.get("AI_OS_DATA_DIR", os.path.join(BASE, "data"))


def state_path() -> str:
    return os.path.join(data_dir(), "state.json")


def table_name() -> str:
    return (os.environ.get("SUPABASE_STATE_TABLE", "") or "state_snapshots").strip()


def log_event(event: str, **details) -> None:
    """تدقيق في `audit.jsonl` — لا يُسقط العملية إن تعذّر التدقيق."""
    try:
        sys.path.insert(0, os.path.join(BASE, "engine"))
        from store import log_event as _log  # type: ignore
        _log(event, **details)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ snapshots
def canonical_text(payload: dict) -> str:
    """تمثيل قانوني مستقر للحالة — أساس البصمة.

    مهم: تخزين الحمولة في عمود `jsonb` يعيد ترتيب مفاتيح الكائن بترتيب
    Postgres الخاص به ولا يحفظ التنسيق الأصلي. لذلك تُحسب البصمة على تمثيل
    مرتَّب المفاتيح وبلا مسافات، فتنجو من رحلة الذهاب والعودة، ويبقى أي تغيير
    حقيقي في القيم كاشفًا. حساب البصمة على بايتات الملف الخام كان يجعل كل
    استعادة تبدو «تالفة» — وهذا ما يمنعه هذا التمثيل.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(payload_text: str) -> str:
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


def payload_digest(payload: dict) -> str:
    return digest(canonical_text(payload))


def read_state(path: str | None = None) -> tuple[dict, str]:
    """يقرأ الحالة من القرص ويعيد (الكائن، نص JSON الموقَّع)."""
    target = path or state_path()
    with open(target, encoding="utf-8") as handle:
        text = handle.read()
    return json.loads(text), text


def snapshot_from(state: dict, reason: str = "manual") -> dict:
    """يبني صف نسخة من كائن الحالة (بلا قرص) — أساس موحّد للدفع والاختبار."""
    meta = state.get("meta") or {}
    return {
        "schema": str(meta.get("schema") or "state/1"),
        "state_version": int(meta.get("version") or 0),
        "reason": (reason or "manual")[:120],
        "sha256": payload_digest(state),           # بصمة التمثيل القانوني
        "byte_size": len(json.dumps(state, ensure_ascii=False).encode("utf-8")),
        "payload": state,
    }


def build_snapshot(reason: str = "manual", path: str | None = None) -> dict:
    state, text = read_state(path)
    snapshot = snapshot_from(state, reason)
    snapshot["byte_size"] = len(text.encode("utf-8"))   # حجم الملف الفعلي على القرص
    return snapshot


def verify_row(row: dict) -> dict:
    """يتحقق من سلامة نسخة مسحوبة: sha256 + الأقسام الأساسية."""
    payload = row.get("payload")
    problems: list[str] = []
    if not isinstance(payload, dict):
        problems.append("الحمولة ليست كائن JSON")
        payload = {}
    stored = str(row.get("sha256") or "")
    recomputed = payload_digest(payload)
    if stored != recomputed:
        problems.append("بصمة sha256 لا تطابق الحمولة — النسخة تالفة أو تغيّرت بعد الكتابة")
    missing = [key for key in REQUIRED_SECTIONS if key not in payload]
    if missing:
        problems.append("أقسام ناقصة: " + ", ".join(missing))
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        problems.append("meta مفقود أو غير صالح")
    return {
        "ok": not problems, "problems": problems,
        "stored_sha256": stored, "recomputed_sha256": recomputed,
        "state_version": (meta or {}).get("version") if isinstance(meta, dict) else None,
        "record_count": sum(len(v) for v in payload.values() if isinstance(v, list)),
    }


def push(reason: str = "manual", *, client: SupabaseClient | None = None) -> dict:
    client = client or SupabaseClient()
    snapshot = build_snapshot(reason)
    rows = client.insert(table_name(), snapshot)
    row = rows[0] if rows else snapshot
    log_event("supabase_snapshot_pushed", table=table_name(), sha256=snapshot["sha256"],
              byte_size=snapshot["byte_size"], reason=snapshot["reason"],
              snapshot_id=row.get("id"))
    return row


def list_snapshots(limit: int = 10, *, client: SupabaseClient | None = None) -> list:
    client = client or SupabaseClient()
    return client.select(table_name(), columns="id,created_at,schema,state_version,reason,sha256,byte_size",
                         order="created_at.desc", limit=limit)


def fetch(snapshot_id: int | None = None, *, client: SupabaseClient | None = None) -> dict:
    client = client or SupabaseClient()
    if snapshot_id in (None, "", "latest"):
        # الترتيب بالمعرّف لا بالوقت: `created_at` قد يتساوى بين نسختين (دفع الدورة
        # ودفع الإنهاء في الثانية نفسها)، وعند التساوي يصبح «الأحدث» غامضًا —
        # فيُستعاد الأقدم بينما الأحدث هو الصحيح. المعرّف تسلسلي متزايد دائمًا،
        # فهو ترتيب الإدخال الحقيقي. (اكتشفه اختبار حقيقي على خادم محلي.)
        rows = client.select(table_name(), order="id.desc", limit=1)
    else:
        rows = client.select(table_name(), filters={"id": f"eq.{int(snapshot_id)}"}, limit=1)
    if not rows:
        raise SupabaseError("لا توجد نسخة مطابقة في Supabase")
    return rows[0]


def restore(snapshot_id: int | None = None, *, apply: bool = False,
            client: SupabaseClient | None = None) -> dict:
    """يستعيد نسخة. بدون `apply` لا يمسّ القرص إطلاقًا."""
    row = fetch(snapshot_id, client=client)
    report = verify_row(row)
    report["snapshot_id"] = row.get("id")
    report["created_at"] = row.get("created_at")
    if not report["ok"]:
        report["applied"] = False
        log_event("supabase_snapshot_restore_blocked", snapshot_id=row.get("id"),
                  problems=report["problems"])
        return report
    if not apply:
        report["applied"] = False
        report["note"] = "معاينة فقط — أضف --apply للكتابة (لا شيء تغيّر على القرص)"
        return report

    target = state_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if os.path.exists(target):
        backup_dir = os.path.join(data_dir(), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        keep = os.path.join(backup_dir, f"state-pre-restore-{stamp}.json")
        shutil.copy2(target, keep)  # نسخ لا نقل: الحالة الأصلية تبقى مكانها
        report["local_backup"] = keep
    temp = f"{target}.tmp-{stamp}"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(row["payload"], handle, ensure_ascii=False, indent=2)
    os.replace(temp, target)  # استبدال ذرّي
    report["applied"] = True
    log_event("supabase_snapshot_restored", snapshot_id=row.get("id"),
              sha256=row.get("sha256"), local_backup=report.get("local_backup"))
    return report


def pull(snapshot_id: int | None = None, *, client: SupabaseClient | None = None,
         target_dir: str | None = None) -> dict:
    """ينزّل نسخة من Supabase إلى قرص محلي — يقفل الدائرة.

    السبب (مهم على الخطة المجانية): Supabase **لا يوفّر نسخًا احتياطية تلقائية**
    ولا PITR إلا في الخطط المدفوعة، ويُوقف المشاريع المجانية بعد 7 أيام بلا نشاط.
    أي أن «السحابة» ليست حصنًا بحد ذاتها: دفعة النسخ نفسها بلا نسخة. لذلك نحتفظ
    بنسخة محلية موقّعة من كل ما في السحابة، فتبقى قابلة للاستعادة في الحالتين:
    فساد القرص المحلي (من السحابة) أو فقدان السحابة (من القرص).
    """
    client = client or SupabaseClient()
    row = fetch(snapshot_id, client=client)
    report = verify_row(row)
    report["snapshot_id"] = row.get("id")
    report["created_at"] = row.get("created_at")
    if not report["ok"]:
        report["written"] = None
        log_event("supabase_snapshot_pull_blocked", snapshot_id=row.get("id"),
                  problems=report["problems"])
        return report

    folder = target_dir or os.path.join(data_dir(), "backups")
    os.makedirs(folder, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(folder, f"supabase-state-{row.get('id')}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(row["payload"], handle, ensure_ascii=False, indent=2)
    report["written"] = path
    log_event("supabase_snapshot_pulled", snapshot_id=row.get("id"),
              sha256=row.get("sha256"), path=path)
    return report


def prune(keep: int = 30, *, client: SupabaseClient | None = None) -> int:
    """يحتفظ بأحدث `keep` نسخة ويحذف ما قبلها."""
    client = client or SupabaseClient()
    rows = client.select(table_name(), columns="id", order="created_at.desc", limit=10000)
    stale = [str(r["id"]) for r in rows[keep:]]
    if not stale:
        return 0
    client.delete(table_name(), match={"id": f"in.({','.join(stale)})"})
    log_event("supabase_snapshot_pruned", deleted=len(stale), kept=keep)
    return len(stale)


# ----------------------------------------------------------------------- CLI
def render_list(rows: list) -> str:
    if not rows:
        return "لا توجد نسخ بعد — ادفع أولى نسخة: python3 -m connectors.supabase_state push"
    lines = ["# | created_at | ver | bytes | reason | sha256"]
    for row in rows:
        lines.append(
            f"{row.get('id')} | {row.get('created_at')} | {row.get('state_version')} | "
            f"{row.get('byte_size')} | {row.get('reason')} | {str(row.get('sha256'))[:12]}…"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="supabase_state", description="Supabase state snapshots")
    sub = parser.add_subparsers(dest="command")

    push_cmd = sub.add_parser("push", help="دفع نسخة كاملة إلى Supabase")
    push_cmd.add_argument("--reason", default="manual")

    list_cmd = sub.add_parser("list", help="عرض أحدث النسخ")
    list_cmd.add_argument("--limit", type=int, default=10)
    list_cmd.add_argument("--json", action="store_true")

    show_cmd = sub.add_parser("show", help="عرض نسخة + التحقق من سلامتها")
    show_cmd.add_argument("--id", default="latest")

    restore_cmd = sub.add_parser("restore", help="استعادة نسخة (معاينة افتراضيًا)")
    restore_cmd.add_argument("--id", default="latest")
    restore_cmd.add_argument("--apply", action="store_true", help="كتابة فعلية إلى state.json")

    pull_cmd = sub.add_parser("pull", help="نزّل نسخة من Supabase إلى قرص محلي")
    pull_cmd.add_argument("--id", default="latest")
    pull_cmd.add_argument("--dir", default="", help="مجلد الهدف (افتراضيًا data/backups/)")

    prune_cmd = sub.add_parser("prune", help="حذف النسخ الأقدم من حد معيّن")
    prune_cmd.add_argument("--keep", type=int, default=30)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    cfg = load_config()
    if not cfg.configured:
        print("❌ Supabase غير مضبوط — راجع docs/supabase-setup.md")
        return 2

    try:
        if args.command == "push":
            if not cfg.can_write:
                summary = cfg.summary()
                print(f"❌ الدفع يحتاج مفتاحًا سريًا مع SUPABASE_WRITE_ENABLED=1.\n   {summary['detail']}")
                return 2
            row = push(args.reason)
            print(f"✅ دُفعت نسخة #{row.get('id')} — {row.get('byte_size')} بايت · "
                  f"sha256 {str(row.get('sha256'))[:12]}…")
            return 0

        if args.command == "list":
            rows = list_snapshots(args.limit)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else render_list(rows))
            return 0

        if args.command == "show":
            row = fetch(args.id)
            report = verify_row(row)
            print(f"نسخة #{row.get('id')} · {row.get('created_at')} · reason={row.get('reason')}")
            print(f"الحجم: {row.get('byte_size')} بايت · الأقسام المُعدّة: {report['record_count']}")
            icon = "✅" if report["ok"] else "❌"
            print(f"{icon} التحقق: {'سليمة' if report['ok'] else ' | '.join(report['problems'])}")
            return 0 if report["ok"] else 2

        if args.command == "restore":
            report = restore(args.id, apply=args.apply)
            if not report["ok"]:
                print("❌ رفض الاستعادة — " + " | ".join(report["problems"]))
                return 2
            if not report["applied"]:
                print(f"🔎 معاينة نسخة #{report['snapshot_id']} ({report['created_at']})\n   {report['note']}")
                return 0
            print(f"✅ استُعيدت نسخة #{report['snapshot_id']} إلى {state_path()}")
            if report.get("local_backup"):
                print(f"   الحالة السابقة محفوظة في: {report['local_backup']}")
            return 0

        if args.command == "pull":
            report = pull(args.id, target_dir=(args.dir or None))
            if not report["ok"]:
                print("❌ رفض التنزيل — " + " | ".join(report["problems"]))
                return 2
            print(f"✅ نُزّلت نسخة #{report['snapshot_id']} إلى: {report['written']}")
            print("   (نسخة محلية موقّعة — تعمل حتى لو تعذّر الوصول إلى Supabase)")
            return 0

        if args.command == "prune":
            if not cfg.can_write:
                print("❌ التقليم يحتاج مفتاحًا سريًا مع SUPABASE_WRITE_ENABLED=1")
                return 2
            count = prune(args.keep)
            print(f"✅ حُذفت {count} نسخة قديمة · المحتفظ به: {args.keep}")
            return 0
    except SupabaseError as exc:
        print(f"❌ {redact(str(exc))}")
        if exc.hint:
            print(f"   تلميح: {exc.hint}")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

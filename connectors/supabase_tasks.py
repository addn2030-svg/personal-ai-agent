# -*- coding: utf-8 -*-
"""مرآة المهام — مزامنة أحادية الاتجاه من `state.json` إلى Supabase.

    state.json  ──sync──▶  public.tasks_mirror      (قابلة لإعادة البناء دائمًا)

لماذا أحادية الاتجاه؟ لأن مصدر الحقيقة الوحيد للمهام هو مخزن الحالة، وعليه تعمل
بوابة الاعتماد (`action_queue`) ومحرك الاستباقية والتدقيق وسجل الحلقات المفتوحة.
لو صار للمهام مصدران لوقع «حجز مزدوج»: مهمة تُغلق في Supabase وتبقى مفتوحة في
النظام، بلا جهة تحكم. المرآة تجلب فائدة الاستعلام (SQL، Table Editor، جوال،
تحليلات) بلا هذه المخاطرة: كل صف هنا مشتق، وأي صف لا يحمل بصمة آخر مزامنة يُحذف.

المزامنة idempotent: معرّف كل صف حتمي من (العنوان + الموعد + المصدر + رقم
التكرار)، فإعادة التشغيل لا تكرّر شيئًا — وتغيير حالة مهمة يُحدّث صفّها لا يُنشئ نسخة.

أوامر:
  python3 -m connectors.supabase_tasks sql          # اطبع SQL الجدول
  python3 -m connectors.supabase_tasks stats        # إحصاء محلي بلا Supabase (يعمل دائمًا)
  python3 -m connectors.supabase_tasks sync         # ادفع المرآة
  python3 -m connectors.supabase_tasks sync --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from connectors.supabase_client import (  # noqa: E402
    SupabaseClient, SupabaseError, load_config, read_sql, redact,
)

SQL_FILE = "02_tasks_mirror.sql"

# مفردات الحالة الفعلية في النظام ← مفردات موحّدة قابلة للاستعلام
STATUS_MAP = {
    "لم تبدأ": "not_started",
    "لم يبدأ": "not_started",
    "جديدة": "not_started",
    "قيد التنفيذ": "in_progress",
    "قيد الانتظار": "in_progress",
    "منجزة": "done",
    "مكتملة": "done",
    "منجز": "done",
    "معلقة": "paused",
    "موقوفة": "paused",
    "ملغاة": "cancelled",
    "ملغى": "cancelled",
}
# مفردات إنجليزية — تصل من أدوات أخرى (GitHub Issues، Notion، Sheets، أي تصدير)
STATUS_MAP_EN = {
    "not_started": "not_started", "todo": "not_started", "pending": "not_started",
    "open": "not_started", "backlog": "not_started", "new": "not_started",
    "in_progress": "in_progress", "in progress": "in_progress", "doing": "in_progress",
    "active": "in_progress", "started": "in_progress", "wip": "in_progress",
    "done": "done", "complete": "done", "completed": "done", "closed": "done",
    "paused": "paused", "on hold": "paused", "on_hold": "paused", "hold": "paused",
    "blocked": "paused",
    "cancelled": "cancelled", "canceled": "cancelled", "dropped": "cancelled",
    "wontfix": "cancelled",
}
CLOSED_NORMS = {"done", "cancelled"}

FIELD_ALIASES = {
    "title": ("العنوان", "title"),
    "kind": ("النوع", "kind"),
    "priority": ("الأولوية", "priority"),
    "status": ("الحالة", "status"),
    "project": ("السياق/المشروع", "المشروع", "project"),
    "source": ("المصدر", "source"),
    "notes": ("ملاحظات", "notes"),
    "due": ("الموعد النهائي", "الموعد", "due_date", "due"),
}


# ------------------------------------------------------------------ mapping
def _field(row: dict, key: str):
    """يقرأ حقلًا من صف المهمة بأي من أسمائه المعروفة (عربي/إنجليزي)."""
    for name in FIELD_ALIASES[key]:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _text(value) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _date(value) -> str | None:
    """يوحّد التواريخ إلى YYYY-MM-DD. أي قيمة غير مفهومة تصبح None (لا تخمين)."""
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_status(raw) -> str:
    """يوحّد مفردات الحالة (عربية أو إنجليزية) إلى قيمة واحدة قابلة للاستعلام.

    ملاحظة مقصودة: ما لا نعرفه يصبح `unknown` لا `not_started` — لا نخمّن أن
    مهمة مجهولة الحالة «لم تبدأ»، لأن ذلك يُخفيها من متابعة المتأخرات.
    """
    text = _text(raw)
    if not text:
        return "not_started"
    if text in STATUS_MAP:
        return STATUS_MAP[text]
    lowered = text.strip().lower()
    if lowered in STATUS_MAP_EN:
        return STATUS_MAP_EN[lowered]
    for key, norm in STATUS_MAP.items():          # مطابقة جزئية للنص العربي
        if key in text:
            return norm
    normalized = lowered.replace("-", "_").replace(" ", "_")
    if normalized in STATUS_MAP_EN:
        return STATUS_MAP_EN[normalized]
    return "unknown"


def task_id(owner: str, title: str, due: str | None, source: str | None, occurrence: int) -> str:
    """معرّف حتمي: نفس المهمة ⇒ نفس المعرّف في كل مزامنة (فتصبح idempotent)."""
    raw = "|".join([owner or "owner", title or "", due or "", source or "", str(occurrence)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def task_rows(state: dict, owner: str = "owner", today: dt.date | None = None) -> list[dict]:
    """يحوّل قسم tasks في الحالة إلى صفوف المرآة (مع الحقول المشتقة)."""
    today = today or dt.date.today()
    rows: list[dict] = []
    seen: dict[str, int] = {}
    for task in (state or {}).get("tasks") or []:
        if not isinstance(task, dict):
            continue
        title = _text(_field(task, "title"))
        if not title:
            continue  # بلا عنوان لا معنى للصف
        due = _date(_field(task, "due"))
        source = _text(_field(task, "source"))
        identity = f"{title}|{due}|{source}"
        seen[identity] = seen.get(identity, 0) + 1

        status_raw = _text(_field(task, "status"))
        status_norm = normalize_status(status_raw or "لم تبدأ")
        is_open = status_norm not in CLOSED_NORMS
        is_overdue = bool(is_open and due and due < today.isoformat())

        rows.append({
            "id": task_id(owner, title, due, source, seen[identity]),
            "owner": owner,
            "title": title,
            "kind": _text(_field(task, "kind")),
            "priority": _text(_field(task, "priority")),
            "status": status_raw,
            "status_norm": status_norm,
            "is_open": is_open,
            "is_overdue": is_overdue,
            "due_date": due,
            "project": _text(_field(task, "project")),
            "source": source,
            "notes": _text(_field(task, "notes")),
            "state_version": int((state.get("meta") or {}).get("version") or 0),
        })
    return rows


# ------------------------------------------------------------------- client
def table_name() -> str:
    return (os.environ.get("SUPABASE_TASKS_TABLE", "") or "tasks_mirror").strip()


def owner_id() -> str:
    explicit = (os.environ.get("SUPABASE_TASKS_OWNER", "") or "").strip()
    if explicit:
        return explicit
    # معرّف مالك البوت (نفس مصدر التملك في engine/telegram_bot.py) إن وُجد
    for candidate in (os.path.join(BASE, "data", ".telegram-owner"),
                      os.path.join(os.environ.get("AI_OS_DATA_DIR", ""), ".telegram-owner")):
        try:
            with open(candidate, encoding="utf-8") as handle:
                value = handle.read().strip()
                if value:
                    return value[:64]
        except (OSError, UnicodeDecodeError):
            continue
    return "owner"


class StateUnavailable(RuntimeError):
    """الحالة غير متاحة أو تالفة.

    مهم جدًا: نفرّق بين «لا مهام في الحالة» (واقع مشروع ⇒ تُفرَّغ المرآة) و
    «لا أستطيع قراءة الحالة» (خطأ ⇒ **نرفض المزامنة**). لو خلطنا بينهما، فخطأ
    مؤقت في المسار أو ملف نصف مكتوب كان سيمسح المرآة كلها في المزامنة التالية.
    """


def read_state(path: str | None = None) -> dict:
    from connectors.supabase_state import read_state as _read
    try:
        state, _text = _read(path)
    except FileNotFoundError as exc:
        raise StateUnavailable(
            f"ملف الحالة غير موجود ({exc.filename}) — تحقق من AI_OS_DATA_DIR"
        ) from None
    except (OSError, ValueError) as exc:
        raise StateUnavailable(f"تعذر قراءة ملف الحالة: {str(exc)[:160]}") from None
    if not isinstance(state, dict):
        raise StateUnavailable("ملف الحالة ليس كائن JSON صالحًا")
    return state


def sync(*, client: SupabaseClient | None = None, state: dict | None = None,
         owner: str | None = None, dry_run: bool = False) -> dict:
    """يدفع المرآة كاملة في دورتين: upsert للصفوف ثم حذف ما لم يُبصم بهذه الدورة."""
    client = client or SupabaseClient()
    state = state if state is not None else read_state()
    owner = owner or owner_id()
    rows = task_rows(state, owner=owner)
    run = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    payload = [{**row, "sync_run": run} for row in rows]

    summary = {
        "run": run, "table": table_name(), "rows": len(payload),
        "open": sum(1 for row in payload if row["is_open"]),
        "overdue": sum(1 for row in payload if row["is_overdue"]),
        "done": sum(1 for row in payload if row["status_norm"] == "done"),
        "dry_run": dry_run,
    }
    if dry_run:
        summary["sample"] = payload[:3]
        return summary

    if payload:
        client.upsert(table_name(), payload, on_conflict="id")
    else:
        # لا مهام أصلًا (حالة سليمة وفارغة): الحذف وحده يجعل المرآة تعكس الواقع.
        # لاحظ أن هذا الفرع لا يُسلك عند تعذّر قراءة الحالة — هناك نرفض قبل أي حذف.
        summary["note"] = "لا مهام في الحالة — تُفرَّغ المرآة"
    deleted = client.delete(table_name(), match={"sync_run": f"neq.{run}"}, returning=True)
    summary["stale_removed"] = len(deleted or [])
    return summary


# -------------------------------------------------------------------- stats
def stats(state: dict | None = None, today: dt.date | None = None) -> dict:
    """إحصاء محلي من state.json — يعمل بلا Supabase وبلا إنترنت.

    إن لم تكن الحالة موجودة بعد (تشغيل أول قبل أول دورة للمدير) نعيد إحصاءً
    فارغًا مع `available=False` ولا نرفع استثناءً — الأمر معلوماتي لا تنفيذي.
    """
    today = today or dt.date.today()
    if state is None:
        try:
            state = read_state()
        except StateUnavailable as exc:
            return {"available": False, "error": str(exc), "total": 0, "open": 0,
                    "overdue": 0, "due_today": 0, "no_due_date": 0, "by_status": {},
                    "by_priority": {}, "by_project": {}, "overdue_rows": [],
                    "today_rows": [], "no_due_rows": [], "state_version": 0}
    rows = task_rows(state, today=today)
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_project: dict[str, int] = {}
    for row in rows:
        by_status[row["status_norm"]] = by_status.get(row["status_norm"], 0) + 1
        if row["is_open"]:
            key = row["priority"] or "بلا أولوية"
            by_priority[key] = by_priority.get(key, 0) + 1
            if row["project"]:
                by_project[row["project"]] = by_project.get(row["project"], 0) + 1
    due_today = [row for row in rows if row["is_open"] and row["due_date"] == today.isoformat()]
    overdue = sorted((row for row in rows if row["is_overdue"]), key=lambda r: r["due_date"] or "")
    no_due = [row for row in rows if row["is_open"] and not row["due_date"]]
    return {
        "available": True,
        "total": len(rows), "open": sum(1 for row in rows if row["is_open"]),
        "overdue": len(overdue), "due_today": len(due_today), "no_due_date": len(no_due),
        "by_status": by_status, "by_priority": by_priority, "by_project": by_project,
        "overdue_rows": overdue[:10], "today_rows": due_today[:10], "no_due_rows": no_due[:10],
        "state_version": int((state.get("meta") or {}).get("version") or 0),
    }


STATUS_LABEL = {
    "not_started": "لم تبدأ", "in_progress": "قيد التنفيذ", "done": "منجزة",
    "paused": "معلقة", "cancelled": "ملغاة", "unknown": "غير محددة",
}


def render_stats(data: dict) -> str:
    if not data.get("available", True):
        return ("📋 المهام: الحالة غير متاحة بعد — " + str(data.get("error", ""))[:160]
                + "\n(تشغيل أول؟ ستظهر المهام بعد أول دورة للمدير.)")
    lines = [
        f"📋 المهام (إصدار الحالة {data['state_version']})",
        f"الإجمالي: {data['total']} · مفتوحة: {data['open']} · متأخرة: {data['overdue']}",
        f"تستحق اليوم: {data['due_today']} · مفتوحة بلا موعد: {data['no_due_date']}",
    ]
    if data["by_status"]:
        parts = [f"{STATUS_LABEL.get(key, key)}: {value}" for key, value in
                 sorted(data["by_status"].items(), key=lambda kv: -kv[1])]
        lines.append("الحالات — " + " · ".join(parts))
    if data["by_priority"]:
        parts = [f"{key}: {value}" for key, value in
                 sorted(data["by_priority"].items(), key=lambda kv: -kv[1])]
        lines.append("الأولوية (مفتوحة) — " + " · ".join(parts))
    if data["overdue_rows"]:
        lines.append("⏰ المتأخرة:")
        for row in data["overdue_rows"]:
            lines.append(f"  • {row['title'][:60]} — {row['due_date']}"
                         + (f" ({row['project']})" if row["project"] else ""))
    if data["today_rows"]:
        lines.append("📅 تستحق اليوم:")
        for row in data["today_rows"]:
            lines.append(f"  • {row['title'][:60]}"
                         + (f" [{row['priority']}]" if row["priority"] else ""))
    return "\n".join(lines)


# ------------------------------------------------------------ manager hook
def daily_due(now: dt.datetime, markers: dict, hour: int | None = None) -> bool:
    """هل حان وقت النسخة اليومية التلقائية؟ (منطق خالص قابل للاختبار)."""
    if os.environ.get("SUPABASE_BACKUP_SCHEDULE_ENABLED", "0") != "1":
        return False
    if not os.environ.get("SUPABASE_URL", "").strip():
        return False
    target = hour
    if target is None:
        try:
            target = int(os.environ.get("SUPABASE_BACKUP_HOUR", "6"))
        except ValueError:
            target = 6
    if now.hour < target:
        return False
    return markers.get("supabase_backup_day") != now.date().isoformat()


def run_daily(*, state: dict | None = None) -> dict:
    """دفعة يومية واحدة: نسخة كاملة (snapshot) + مزامنة المرآة. لا تُسقط أي حلقة."""
    from connectors import supabase_state
    result: dict = {"snapshot": None, "mirror": None, "errors": []}

    # قراءة الحالة أولًا (قبل أي عمل شبكي): إن تعذّرت، نتوقف فورًا بلا نسخة
    # ولا مزامنة — فلا نمسح المرآة بسبب خطأ قراءة (تشغيل أول أو مسار خاطئ).
    if state is None:
        try:
            state = read_state()
        except StateUnavailable as exc:
            result["errors"].append(f"state: {exc}")
            return result

    try:
        row = supabase_state.push("نسخة يومية تلقائية")
        result["snapshot"] = {"id": row.get("id"), "byte_size": row.get("byte_size")}
    except (SupabaseError, OSError, ValueError) as exc:
        result["errors"].append(f"snapshot: {exc}")
    try:
        result["mirror"] = sync(state=state)
    except (SupabaseError, StateUnavailable) as exc:
        result["errors"].append(f"mirror: {exc}")
    return result


# ---------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="supabase_tasks", description="مرآة المهام في Supabase")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("sql", help="اطبع SQL إنشاء الجدول")
    sub.add_parser("stats", help="إحصاء محلي من state.json (بلا شبكة)")
    sync_cmd = sub.add_parser("sync", help="ادفع المرآة إلى Supabase")
    sync_cmd.add_argument("--dry-run", action="store_true", help="اعرض ما سيُرسل بلا كتابة")
    args = parser.parse_args(argv)
    command = args.command or "stats"

    if command == "sql":
        sql = read_sql(SQL_FILE)
        if not sql:
            print(f"❌ ملف SQL غير موجود: supabase/{SQL_FILE}")
            return 2
        print(sql)
        return 0

    try:
        if command == "stats":
            print(render_stats(stats()))
            return 0
        if command == "sync":
            cfg = load_config()
            if not cfg.configured:
                print("❌ Supabase غير مضبوط — راجع docs/supabase-setup.md")
                return 2
            if not cfg.can_write:
                print(f"❌ المزامنة تحتاج مفتاحًا سريًا مع SUPABASE_WRITE_ENABLED=1.\n   {cfg.summary()['detail']}")
                return 2
            summary = sync(dry_run=getattr(args, "dry_run", False))
            if summary["dry_run"]:
                print(f"🔎 معاينة: {summary['rows']} صفًا ستُرسل (مفتوحة {summary['open']} · "
                      f"متأخرة {summary['overdue']} · منجزة {summary['done']})")
                for row in summary["sample"]:
                    print(f"   • {row['title'][:50]} · {row['status_norm']} · {row['due_date'] or '—'}")
                return 0
            print(f"✅ زُوّجت المرآة — {summary['rows']} صفًا (مفتوحة {summary['open']} · "
                  f"متأخرة {summary['overdue']}) · حُذف {summary['stale_removed']} صفًا قديمًا")
            return 0
    except StateUnavailable as exc:
        # رفض مقصود: لا نمسح المرآة لأن الحالة تعذّرت قراءتها
        print(f"❌ {redact(str(exc))}")
        print("   لم تُمس المرآة (لا كتابة ولا حذف) — أصلح الحالة ثم أعد المحاولة.")
        return 2
    except SupabaseError as exc:
        print(f"❌ {redact(str(exc))}")
        if exc.hint:
            print(f"   تلميح: {exc.hint}")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

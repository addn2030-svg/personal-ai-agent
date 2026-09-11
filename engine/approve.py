# -*- coding: utf-8 -*-
"""
بوابة الاعتماد البشرية (إصلاح C2) — واجهة سطر أوامر لطابور الإجراءات.

  python3 engine/approve.py list
  python3 engine/approve.py approve A-001 --hash <bصمة المحتوى>
  python3 engine/approve.py reject   A-001 --reason "..."
  python3 engine/approve.py executed A-001          # تأكيد التنفيذ (يدويًا حتى تتصل أدوات الإرسال)
  python3 engine/approve.py expire                    # إنهاء صلاحية المتقادم
  python3 engine/approve.py draft رسالة.md [--type note] [--channel email] [--expires 2]
                                                    # أي نص → مسودة في الطابور (لا إرسال)
  python3 engine/approve.py draft -                   # من stdin / أنبوب

القواعد:
- الاعتماد مرتبط ببصمة محتوى الإجراء (content_hash) — أي تغيير في النص يُبطل الأمر.
- الإجراء المعتمد تنتهي صلاحيته بعد يومين من إنشائه إن لم يُعتمد.
- كل عملية تُسجَّل في audit.jsonl.
"""
import argparse
import datetime as dt
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

STATUS_AR = {"PENDING_APPROVAL": "⏳ بانتظار الاعتماد", "APPROVED": "✅ معتمد — جاهز للتنفيذ",
             "EXECUTED": "📤 نُفّذ", "EXPIRED": "🕐 انتهت صلاحيته", "REJECTED": "🚫 مرفوض"}

def _as_date(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])

def fmt(a):
    return (f"{a['action_id']}  {STATUS_AR.get(a['status'], a['status'])}  "
            f"[{a['type']}]  أنشئ {a['created_at']}  ينتهي {a['expires_at']}\n"
            f"   البصمة: {a['content_hash']}\n"
            f"   المحتوى: {a['content'][:90].replace(chr(10), ' ')}...")

def _enqueue_draft(store, body, a_type, channel, expires_days, origin):
    """إدراج مسودة بالبصمة نفسها التي تعتمد عليها بوابة C2 (idempotent)."""
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def mutate(S):
        queue = S.get("action_queue", [])
        hit = next((a for a in queue if a.get("content_hash") == h), None)
        if hit:
            return False, ("exists", hit)
        today = dt.date.today()
        row = {"action_id": f"A-{len(queue) + 1:03d}", "type": a_type, "channel": channel,
               "content": body, "content_hash": h, "status": "PENDING_APPROVAL",
               "created_at": today.isoformat(),
               "expires_at": (today + dt.timedelta(days=max(1, int(expires_days)))).isoformat(),
               "approved_at": None, "executed_at": None, "origin": origin}
        S["action_queue"] = queue + [row]
        return True, ("created", row)

    return store.transaction(mutate, "action_draft_enqueued", hash=h, type=a_type)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "approve", "reject", "executed", "expire", "draft"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--hash", dest="chash")
    ap.add_argument("--reason", default="")
    ap.add_argument("--type", dest="a_type", default="manual_note")
    ap.add_argument("--channel", default="internal")
    ap.add_argument("--expires", type=int, default=2)
    ap.add_argument("--origin", default="manual:approve.py")
    args = ap.parse_args()

    store = Store()

    if args.cmd == "draft":
        if not args.id:
            print("❌ صيغة: python3 engine/approve.py draft <ملف|-> …")
            sys.exit(1)
        if args.id == "-":
            body = sys.stdin.read()
        else:
            path = args.id if os.path.exists(args.id) else os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.id)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
        body = body.strip()
        if not body:
            print("❌ المسودة فارغة.")
            sys.exit(1)
        state, row = _enqueue_draft(store, body, args.a_type, args.channel,
                                   args.expires, args.origin)
        if state == "exists":
            print(f"🔁 المسودة موجودة في الطابور: {row['action_id']} "
                  f"[{row['status']}] — بصمة {row['content_hash']}")
        else:
            print(f"✅ أُدرجت مسودة: {row['action_id']} [{args.a_type} → {args.channel}] "
                  f"بانتظار اعتمادك — لا إرسال تلقائي.")
            print(f"   للاعتماد: python3 engine/approve.py approve {row['action_id']} "
                  f"--hash {row['content_hash']}")
        return
    S = store.rows_all()
    q = S.get("action_queue", [])
    today = dt.date.today()

    # إنهاء صلاحية المتقادم تلقائيًا عند أي عملية
    changed = False
    for a in q:
        if a["status"] == "PENDING_APPROVAL" and _as_date(a["expires_at"]) < today:
            a["status"] = "EXPIRED"
            changed = True
            log_event("action_expired", action_id=a["action_id"])

    if args.cmd == "list":
        if changed:
            store.commit(S, "expire_actions")
            q = store.rows_all()["action_queue"]
        if not q:
            print("طابور الإجراءات فارغ.")
        for a in q:
            print(fmt(a) + "\n")
        return

    act = next((a for a in q if a["action_id"] == args.id), None)
    if not act:
        print(f"❌ لا يوجد إجراء بالمعرف {args.id}")
        sys.exit(1)

    if args.cmd == "approve":
        if act["status"] != "PENDING_APPROVAL":
            print(f"❌ حالته الحالية: {STATUS_AR[act['status']]} — لا يمكن اعتماده.")
            sys.exit(1)
        if not args.chash or args.chash.strip() != act["content_hash"]:
            print("❌ بصمة المحتوى غير مطابقة — رفض الاعتماد.")
            print("   (قاعدة C2: الاعتماد مرتبط بالنص حرفيًا؛ انسخ الأمر من صفحة approvals)")
            log_event("approval_denied", action_id=act["action_id"], reason="hash_mismatch")
            sys.exit(2)
        act["status"] = "APPROVED"
        act["approved_at"] = today.isoformat()
        log_event("action_approved", action_id=act["action_id"], hash=act["content_hash"])
    elif args.cmd == "reject":
        act["status"] = "REJECTED"
        log_event("action_rejected", action_id=act["action_id"], reason=args.reason)
    elif args.cmd == "executed":
        if act["status"] != "APPROVED":
            print("❌ لا يمكن تأكيد تنفيذ إجراء غير معتمد.")
            sys.exit(1)
        act["status"] = "EXECUTED"
        act["executed_at"] = today.isoformat()
        log_event("action_executed", action_id=act["action_id"])

    store.commit(S, f"action_{args.cmd}", action_id=act["action_id"])
    print(f"✅ {act['action_id']} → {STATUS_AR[act['status']]}")

if __name__ == "__main__":
    main()

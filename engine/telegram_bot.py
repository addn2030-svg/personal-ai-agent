# -*- coding: utf-8 -*-
"""
Telegram Approval Inbox + Chief of Staff Bot — بلا اعتماديات خارجية (urllib فقط).
الوظائف: بريف فوري · طابور الاعتماد بأزرار (مربوط بالبصمة C2) · حل طلبات القرار ·
مراجعات التعلّم · باب اليوم · التقاط أي نص إلى صندوق يومك · إشعارات تلقائية بالمستجدات.

التهيئة (دقيقتان — راجع docs/telegram-setup.md):
  1) @BotFather ← /newbot ← خذ التوكن
  2) شغّل البوت وأرسل /start من جوالك — أول محادثة تملك القناة (من بعدها: أي معرف آخر يُرفض ويُسجل أمنيًا)
  3) TELEGRAM_BOT_TOKEN=xxx python3 engine/telegram_bot.py

اختبار بدون تفعيل:  python3 engine/telegram_bot.py --test
"""
import datetime as dt
import glob
import json
import os
import sys
import re
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_FILE = os.path.join(BASE, "data", ".telegram-owner")
MARKERS = os.path.join(BASE, "data", ".telegram-markers.json")
API = f"https://api.telegram.org/bot{TOKEN}"


def api(method, _timeout=25, **params):
    if not TOKEN:
        return None
    data = json.dumps(params).encode()
    req = urllib.request.Request(API + "/" + method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=_timeout).read())
    except Exception as e:
        log_event("telegram_error", method=method, error=str(e)[:120])
        return None


# ---------------------------------------------------------------- الأمان: مالك واحد
def owner_id():
    try:
        return open(OWNER_FILE).read().strip()
    except Exception:
        return ""


def authorized(chat_id):
    return owner_id() == "" or str(chat_id) == owner_id()


def claim_or_verify(chat_id):
    """أول محادثة تملك القناة — ما بعدها يُرفض ويوثق أمنيًا."""
    if owner_id() == "":
        open(OWNER_FILE, "w").write(str(chat_id))
        log_event("telegram_owner_claimed", chat=str(chat_id))
        return True, True
    return (str(chat_id) == owner_id()), False


# ---------------------------------------------------------------- عارضات الحالة
def brief_text():
    files = sorted(glob.glob(os.path.join(BASE, "reports", "daily-brief-*.md")), reverse=True)
    if files:
        txt = open(files[0], encoding="utf-8").read()
        return "🌅 أحدث بريف:\n\n" + txt[:3500] + ("\n…(النسخة الكاملة في اللوحة)" if len(txt) > 3500 else "")
    return "لا بريف بعد — شغّل python3 engine/manager.py full"


def tasks_text():
    S = Store().rows_all()
    op = [t for t in S["tasks"] if t.get("الحالة") != "منجزة"]
    op.sort(key=lambda t: {"عالية": 0, "متوسطة": 1}.get(t.get("الأولوية"), 2))
    lines = [f"• [{t.get('الأولوية')}] {t['العنوان'][:60]}" for t in op[:8]]
    return "📋 أهم المهام المفتوحة:\n" + "\n".join(lines) + f"\n(الإجمالي: {len(op)})"


def decisions_keyboard():
    S = Store().rows_all()
    drs = [d for d in S.get("decision_requests", []) if d["status"] == "PENDING"]
    if not drs:
        return "لا طلبات قرار مفتوحة ✅", None
    kb = []
    lines = []
    for d in drs[:4]:
        lines.append(f"🧭 {d['id']}: {d['title'][:80]}\nالمهلة {str(d.get('deadline'))[:10]}")
        row = [{"text": f"{chr(65+i)} ✅ {d['id']}", "callback_data": f"dr:{d['id']}:{i+1}"} for i in range(len(d["options"][:3]))]
        kb.append(row)
    return "\n\n".join(lines), {"inline_keyboard": kb}


def approvals_keyboard():
    S = Store().rows_all()
    pend = [a for a in S["action_queue"] if a["status"] == "PENDING_APPROVAL"]
    if not pend:
        return "لا إجراءات بانتظار الاعتماد ✅", None
    kb, lines = [], []
    for a in pend[:5]:
        lines.append(f"🛂 {a['action_id']} [{a['type']}]\n{a['content'][:220]}…\n(ينتهي {a['expires_at']})")
        kb.append([{"text": f"✅ اعتماد {a['action_id']}", "callback_data": f"ap:{a['action_id']}:{a['content_hash'][:8]}"},
                   {"text": f"❌ رفض {a['action_id']}", "callback_data": f"rj:{a['action_id']}"}])
    return "\n\n".join(lines), {"inline_keyboard": kb}


def reviews_text():
    S = Store().rows_all()
    due = [r for r in S.get("learning_reviews", []) if r["status"] in ("DUE", "PRESENTED")]
    if not due:
        return "لا مراجعات مستحقة اليوم ✅"
    return "📚 مراجعات اليوم:\n" + "\n".join(f"• {r['concept_title']} ({r['est_minutes']} د) — {r['review_id']}" for r in due[:4]) + \
        "\nبعد الإجابة أرسل: /answer " + due[0]["review_id"] + " 85"


def door_text():
    from chief_of_staff import WEEK_DOORS  # خريطة الأبواب من المحرك نفسه
    t = dt.date.today()
    d = WEEK_DOORS.get(t.weekday(), ("—", ""))
    return f"🚪 باب اليوم ({t.isoformat()}): {d[0]}\n{d[1]}"


# ---------------------------------------------------------------- معالجات
def handle(msg):
    chat = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    ok, claimed = claim_or_verify(chat)
    if not ok:
        api("sendMessage", chat_id=chat, text="⛔ هذه قناة مملوكة — غير مصرح لك.")
        log_event("telegram_unauthorized_access", chat=chat, text=text[:60])
        return
    if claimed:
        api("sendMessage", chat_id=chat, text="✅ تم ربط جوالك بالنظام — أنت المالك. جرّب: /brief")
        return

    if text.startswith("/brief"):
        api("sendMessage", chat_id=chat, text=brief_text())
    elif text.startswith("/tasks"):
        api("sendMessage", chat_id=chat, text=tasks_text())
    elif text.startswith("/decisions"):
        t, kb = decisions_keyboard()
        api("sendMessage", chat_id=chat, text=t, reply_markup=kb)
    elif text.startswith("/approve"):
        t, kb = approvals_keyboard()
        api("sendMessage", chat_id=chat, text=t, reply_markup=kb)
    elif text.startswith("/reviews"):
        api("sendMessage", chat_id=chat, text=reviews_text())
    elif text.startswith("/door"):
        api("sendMessage", chat_id=chat, text=door_text())
    elif text.startswith("/mastery"):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(BASE, "engine", "learning_engine.py"), "mastery"],
                           capture_output=True, text=True)
        api("sendMessage", chat_id=chat, text="🗺️ خريطة الإتقان:\n" + (r.stdout or "—")[:3000])
    elif text.startswith("/answer"):
        parts = text.split()
        try:
            rid, score = parts[1], int(parts[2])
            from learning_engine import cmd_answer
            cmd_answer(rid, score)
            api("sendMessage", chat_id=chat, text=f"✅ سُجلت {rid} = {score}%")
        except SystemExit:
            raise
        except Exception as e:
            api("sendMessage", chat_id=chat, text=f"صيغة: /answer LR-001 85\n{e}")
    elif text.startswith("/help") or text.startswith("/start"):
        api("sendMessage", chat_id=chat, text=("الأوامر:\n/brief البريف • /tasks المهام • /decisions القرارات بأزرار\n"
                                               "/approve الاعتمادات بأزرار • /reviews مراجعات اليوم • /answer LR-001 85\n"
                                               "/door باب اليوم • /mastery خريطة الإتقان\n"
                                               "وأي نص ترسله = يُلتقط في صندوق يومك تلقائيًا 📥"))
    elif text and re.match(r"^طاق[هة]?\s*(\d{1,2}).*ارهاق", text.replace("إرهاق", "ارهاق")):
        m = re.match(r"^طاق[هة]?\s*(\d{1,2}).*ارهاق\s*(\d{1,2})", text.replace("إرهاق", "ارهاق"))
        if m and 1 <= int(m.group(1)) <= 10 and 1 <= int(m.group(2)) <= 10:
            from energy_log import log as elog
            elog(int(m.group(1)), int(m.group(2)), "من تيليجرام")
            api("sendMessage", chat_id=chat, text="🔋 سُجل — تعافيك يُقاس الآن")
        else:
            api("sendMessage", chat_id=chat, text="صيغة: طاقة 7 إرهاق 3 (من 1 إلى 10)")
    elif text.startswith("/okr"):
        import subprocess
        args = text.split()[1:]
        r = subprocess.run([sys.executable, os.path.join(BASE, "engine", "okr.py")] + args,
                           capture_output=True, text=True)
        api("sendMessage", chat_id=chat, text=(r.stdout or r.stderr or "—")[:1500])
    elif msg.get("voice") or msg.get("document") or msg.get("audio"):
        import csv as _csv
        inbox = os.path.join(BASE, "data", "inbox.csv")
        new = not os.path.exists(inbox)
        with open(inbox, "a", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            if new: w.writerow(["التصنيف","العنوان","النوع","الأولوية","الموعد","ملاحظة"])
            w.writerow(["مهمة", "🎙️ رسالة صوتية/ملف من تيليجرام — يحتاج تفريغًا", "قسم", "متوسطة", "", dt.date.today().isoformat()])
        log_event("TELEGRAM_VOICE_CAPTURED")
        api("sendMessage", chat_id=chat, text="🎙️ وصلت — سُجلت في صندوق يومك (التفريغ النصي مرحلة قادمة؛ أرسل نصها لاحقًا إن استعجلت)")
    else:
        # التقاط: أي نص → صندوق اليوم (يُصنف عند الاستيراد)
        import csv as _csv
        inbox = os.path.join(BASE, "data", "inbox.csv")
        new = not os.path.exists(inbox)
        with open(inbox, "a", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            if new:
                w.writerow(["التصنيف", "العنوان", "النوع", "الأولوية", "الموعد", "ملاحظة"])
            w.writerow(["مهمة", text[:120], "قسم", "متوسطة", "", f"من تيليجرام {dt.date.today()}"])
        log_event("TELEGRAM_CAPTURED", chars=len(text))
        api("sendMessage", chat_id=chat, text="📥 التُقط في صندوق يومك — سيُصنف مع الدورة القادمة")


def handle_callback(cb):
    chat = str(cb["message"]["chat"]["id"])
    if not authorized(chat):
        api("answerCallbackQuery", callback_query_id=cb["id"], text="⛔ غير مصرح")
        return
    data = cb["data"]
    if data.startswith("ap:"):
        _, aid, h8 = data.split(":")
        st = Store(); S = st.rows_all()
        act = next((a for a in S["action_queue"] if a["action_id"] == aid), None)
        if not act or act["status"] != "PENDING_APPROVAL":
            api("answerCallbackQuery", callback_query_id=cb["id"], text="غير متاح")
            return
        if act["content_hash"][:8] != h8:  # قاعدة C2: الاعتماد مربوط بالبصمة
            act["status"] = "REJECTED"; st.commit(S, "telegram_hash_mismatch", action=aid)
            log_event("approval_denied", action_id=aid, reason="telegram_hash_mismatch")
            api("answerCallbackQuery", callback_query_id=cb["id"], text="❌ بصمة غير مطابقة — رُفض")
            return
        act["status"] = "APPROVED"; act["approved_at"] = dt.date.today().isoformat()
        st.commit(S, "telegram_approved", action=aid)
        log_event("action_approved", action_id=aid, via="telegram")
        api("answerCallbackQuery", callback_query_id=cb["id"], text=f"✅ {aid} اعتُمد")
        api("sendMessage", chat_id=chat, text=f"✅ {aid} معتمد — نفّذ المحتوى من صفحة الاعتماد ثم: python3 engine/approve.py executed {aid}")
    elif data.startswith("rj:"):
        _, aid = data.split(":", 1)
        st = Store(); S = st.rows_all()
        act = next((a for a in S["action_queue"] if a["action_id"] == aid), None)
        if act and act["status"] == "PENDING_APPROVAL":
            act["status"] = "REJECTED"
            st.commit(S, "telegram_rejected", action=aid)
            log_event("action_rejected", action_id=aid, via="telegram")
        api("answerCallbackQuery", callback_query_id=cb["id"], text=f"🚫 {aid} رُفض")
    elif data.startswith("dr:"):
        _, did, opt = data.split(":")
        from manager import resolve_dr
        try:
            resolve_dr(did, int(opt), note="من تيليجرام")
            api("answerCallbackQuery", callback_query_id=cb["id"], text=f"✅ {did} حُسم")
        except SystemExit:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="تعذر الحسم")
        except Exception as e:
            api("answerCallbackQuery", callback_query_id=cb["id"], text=str(e)[:120])


# ---------------------------------------------------------------- إشعارات المستجدات
def markers():
    try:
        return json.load(open(MARKERS))
    except Exception:
        return {}


def notify_new():
    """يدفع الجديد إلى مالك القناة: إجراءات معلقة لم تُبلغ + بريف الصباح."""
    own = owner_id()
    if not own or not TOKEN:
        return
    m = markers()
    S = Store().rows_all()
    changed = False
    for a in S["action_queue"]:
        if a["status"] == "PENDING_APPROVAL" and not a.get("notified"):
            t, kb = None, None
            kb = {"inline_keyboard": [[
                {"text": "✅ اعتماد", "callback_data": f"ap:{a['action_id']}:{a['content_hash'][:8]}"},
                {"text": "❌ رفض", "callback_data": f"rj:{a['action_id']}"}]]}
            res = api("sendMessage", chat_id=int(own),
                       text=f"🛂 إجراء جديد بانتظارك: {a['action_id']}\n{a['content'][:250]}…\nينتهي: {a['expires_at']}",
                       reply_markup=kb)
            if res and res.get("ok"):
                a["notified"] = True
                changed = True
    if changed:
        st = Store(); st.data["action_queue"] = [a for a in Store().data["action_queue"]]
        # نعيد الكتابة بأمان عبر rows_all
        st2 = Store(); S2 = st2.rows_all()
        for a2 in S2["action_queue"]:
            for a in S["action_queue"]:
                if a2["action_id"] == a["action_id"] and a.get("notified"):
                    a2["notified"] = True
        st2.commit(S2, "telegram_notified")
    # بريف الصباح (6–9 صباحًا، مرة يوميًا)
    now = dt.datetime.now()
    if 6 <= now.hour < 9 and m.get("brief_day") != now.date().isoformat():
        api("sendMessage", chat_id=int(own), text=brief_text()[:3500])
        m["brief_day"] = now.date().isoformat()
        json.dump(m, open(MARKERS, "w"))


# ---------------------------------------------------------------- الحلقة
def run():
    if not TOKEN:
        print("⚠️ عيّن المتغير: TELEGRAM_BOT_TOKEN — راجع docs/telegram-setup.md")
        return
    print("🤖 بوت النظام يعمل (polling) — Ctrl+C للإيقاف")
    offset = markers().get("offset", 0)
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=30, _timeout=40)
            for u in (res or {}).get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
                elif "callback_query" in u:
                    handle_callback(u["callback_query"])
            m = markers(); m["offset"] = offset; json.dump(m, open(MARKERS, "w"))
            notify_new()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log_event("telegram_loop_error", error=str(e)[:120])
            time.sleep(5)


def test():
    """اختبار المنطق بلا شبكة — يتحقق أن كل العارضات تعمل على الحالة الحقيقية."""
    print("── وضع الاختبار (بلا شبكة) ──")
    print(door_text()); print()
    print(tasks_text()[:200] + "…"); print()
    print(reviews_text()); print()
    t, kb = decisions_keyboard()
    print(t[:200])
    assert kb is not None and kb["inline_keyboard"], "لوحة القرارات فارغة!"
    t2, kb2 = approvals_keyboard()
    print(f"الاعتمادات المعلقة المعروضة: {'موجودة' if kb2 else 'لا شيء'}")
    print("✅ كل العارضات واللوحات سليمة")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    else:
        run()

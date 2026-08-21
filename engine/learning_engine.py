# -*- coding: utf-8 -*-
"""
Personal Adaptive Teaching Engine — الطبقة الحتمية (v0.4).
التعليم الحي (شرح/أسئلة/تغذية راجعة) في prompts/personal-training.md؛
هذا المحرك يدير ما يجب أن يكون حتميًا: خطط التعلّم، خريطة الإتقان،
دورة حياة المراجعات، والتكيّف بالدرجات.

دورة حياة المراجعة (تصحيح المواصفة — الإشعار ليس تعلّمًا):
  SCHEDULED → DUE → PRESENTED → ANSWERED → SCORED → COMPLETED
وكل مفهوم ضعيف له جدولته المستقلة (لا دمج weak_areas).
learning_reviews منفصلة تمامًا عن ActionQueue (الطابور للأفعال الخارجية فقط).

الأوامر:
  python3 engine/learning_engine.py plan "العنوان" --parts 6 --goal "..." --titles "أ|ب|ج"
  python3 engine/learning_engine.py start LP-001
  python3 engine/learning_engine.py score LP-001 1 78
  python3 engine/learning_engine.py final LP-001
  python3 engine/learning_engine.py due
  python3 engine/learning_engine.py present LR-001
  python3 engine/learning_engine.py answer LR-001 85
  python3 engine/learning_engine.py mastery
"""
import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()
INTERVALS = [1, 3, 7, 14, 30]  # سلم التكرار المتباعد (أيامًا)

def _verdict(score):
    """التكيّف الإلزامي حسب المواصفة."""
    if score >= 85:
        return "تقدّم بثقة (ارفع الصعوبة في الجزء التالي)"
    if score >= 70:
        return "تقدّم + بند تعزيز واحد قبل الجزء التالي"
    if score >= 50:
        return "إعادة شرح موجزة + سؤال آخر على نفس الجزء"
    return "عُد إلى المتطلب السابق قبل الاستمرار"

def _ema(old, new, alpha=0.6):
    return round(alpha * new + (1 - alpha) * old) if old is not None else new

def _flag(name, *vals):
    return "--" + name in sys.argv

def _val(name, default=None):
    if f"--{name}" in sys.argv:
        i = sys.argv.index(f"--{name}")
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def _load():
    st = Store()
    return st, st.rows_all()


def cmd_plan(title, parts, goal, domain, titles):
    st, S = _load()
    sec_titles = [t.strip() for t in (titles or "").split("|")]
    plan = {"plan_id": f"LP-{len(S['learning_plans']) + 1:03d}", "title": title,
            "goal": goal or "كفاءة عملية قابلة للتطبيق", "domain": domain or "عام",
            "target_level": "كفاءة عملية تطبيقية", "current_level": "يُقيّم عند البدء (3 أسئلة قياسية)",
            "estimated_sessions": parts, "status": "PLANNED", "current_part": 0,
            "session_minutes": min(90, int(_val("minutes", 45))),  # قاعدة 90/20/10: الجلسة ≤90 دقيقة
            "created_at": TODAY.isoformat(),
            "sections": [{"part": i, "title": sec_titles[i - 1] if i <= len(sec_titles) else f"الجزء {i}",
                          "objective": None, "status": "NOT_STARTED"} for i in range(1, parts + 1)],
            "final_case": None, "final_test": None, "real_world_assignment": None,
            "review_plan": INTERVALS}
    S["learning_plans"].append(plan)
    st.commit(S, "learning_plan_created", plan=plan["plan_id"], title=title[:40])
    log_event("LEARNING_PLAN_CREATED", plan=plan["plan_id"], parts=parts)
    print(f"📚 {plan['plan_id']} — «{title}»")
    print(f"   الهدف: {plan['goal']} | الجلسات المتوقعة: {parts} | الحالة: PLANNED")
    print("   خريطة التعلّم: " + " ← ".join(s["title"] for s in plan["sections"]))
    print("   ▶️ ابدأ:  python3 engine/learning_engine.py start " + plan["plan_id"])
    print("   (التدريس الحي وفق بروتوكول التدريب الإلزامي في prompts/personal-training.md)")


def _plan(S, pid):
    return next((p for p in S["learning_plans"] if p["plan_id"] == pid), None)


def _concept(S, pid, part_no, title, domain):
    cid = f"{pid}-P{part_no}"
    c = next((x for x in S["learning_concepts"] if x["concept_id"] == cid), None)
    if not c:
        c = {"concept_id": cid, "title": title, "domain": domain,
             "mastery": {"knowledge": None, "reasoning": None, "application": None, "practical_skill": None},
             "confidence": None, "misconception_flags": [], "last_tested": None,
             "last_score": None, "next_review": None, "history": []}
        S["learning_concepts"].append(c)
    return c


def cmd_start(pid):
    st, S = _load()
    p = _plan(S, pid)
    if not p:
        sys.exit(f"❌ لا توجد خطة {pid}")
    p["status"], p["current_part"] = "ACTIVE", 1
    p["sections"][0]["status"] = "IN_PROGRESS"
    st.commit(S, "learning_started", plan=pid)
    log_event("LEARNING_STARTED", plan=pid)
    print(f"▶️ {pid} نشِطة — نبدأ بالجزء 1: {p['sections'][0]['title']}")


def cmd_score(pid, part_no, score):
    st, S = _load()
    p = _plan(S, pid)
    if not p or p["status"] not in ("ACTIVE", "AWAITING_FINAL"):
        sys.exit("❌ الخطة غير نشطة")
    sec = next((s for s in p["sections"] if s["part"] == part_no), None)
    if not sec:
        sys.exit(f"❌ لا يوجد جزء {part_no}")
    score = max(0, min(100, int(score)))
    c = _concept(S, pid, part_no, sec["title"], p["domain"])
    k = int(_val("knowledge", score)); r = int(_val("reasoning", score)); a = int(_val("application", score))
    c["mastery"]["knowledge"] = _ema(c["mastery"]["knowledge"], k)
    c["mastery"]["reasoning"] = _ema(c["mastery"]["reasoning"], r)
    c["mastery"]["application"] = _ema(c["mastery"]["application"], a)
    c["last_tested"], c["last_score"] = TODAY.isoformat(), score
    c["history"].append({"date": TODAY.isoformat(), "score": score, "part": part_no})
    passed = score >= 70
    sec["status"] = "PASSED" if passed else "RETEACH"
    if score < 70:
        c["misconception_flags"].append(f"P{part_no}@{TODAY}: درجة {score}")
    if score >= 50 and p["current_part"] == part_no:
        p["current_part"] = min(part_no + 1, len(p["sections"]))
        if p["current_part"] <= len(p["sections"]) and p["current_part"] != part_no:
            p["sections"][p["current_part"] - 1]["status"] = "IN_PROGRESS"
    if all(s["status"] == "PASSED" for s in p["sections"]):
        p["status"] = "AWAITING_FINAL"
    st.commit(S, "learning_scored", plan=pid, part=part_no, score=score)
    log_event("LEARNING_SCORED", plan=pid, part=part_no, score=score, passed=passed)
    print(f"📊 الجزء {part_no} «{sec['title']}» → {score}% | الحكم: {_verdict(score)}")
    print(f"   الإتقان الآن: معرفة {c['mastery']['knowledge']}% | استدلال {c['mastery']['reasoning']}% | تطبيق {c['mastery']['application']}%")
    if score < 70:
        print("   ⚠️ سوء فهم مُسجَّل — سيدخل التكرار المتباعد من الغد أو اليوم عند الإنهاء.")
    if p["status"] == "AWAITING_FINAL":
        print("   🏁 اكتملت الأجزاء — نفّذ:  final " + pid)


def cmd_final(pid):
    st, S = _load()
    p = _plan(S, pid)
    if not p:
        sys.exit(f"❌ لا توجد خطة {pid}")
    concepts = [c for c in S["learning_concepts"] if c["concept_id"].startswith(pid)]
    k = round(sum(c["mastery"]["knowledge"] for c in concepts) / len(concepts))
    r = round(sum(c["mastery"]["reasoning"] for c in concepts) / len(concepts))
    a = round(sum(c["mastery"]["application"] for c in concepts) / len(concepts))
    p["status"], p["final_test"] = "COMPLETED", TODAY.isoformat()
    # جدولة المراجعات: الأضعف (إتقان<75) يبدأ اليوم، والبقية غدًا — كل مفهوم باستقلال
    created = []
    for c in concepts:
        avg = round((c["mastery"]["knowledge"] + c["mastery"]["reasoning"] + c["mastery"]["application"]) / 3)
        due = TODAY if avg < 75 else TODAY + dt.timedelta(days=1)
        S["learning_reviews"].append({"review_id": f"LR-{len(S['learning_reviews']) + 1:03d}",
                                      "plan_id": pid, "concept_id": c["concept_id"], "concept_title": c["title"],
                                      "status": "SCHEDULED", "due_date": due.isoformat(),
                                      "interval_idx": 0, "est_minutes": 7, "created_at": TODAY.isoformat(),
                                      "presented_at": None, "answered_at": None})
        c["next_review"] = due.isoformat()
        created.append((c["title"], due.isoformat()))
    st.commit(S, "learning_final", plan=pid, k=k, r=r, a=a)
    log_event("LEARNING_FINAL", plan=pid)
    weak = [c for c in concepts if any(c["misconception_flags"]) or
            round(sum(v for v in c["mastery"].values() if v is not None) / 3) < 75]
    print(f"🏁 {pid} — «{p['title']}» :: COMPETENCY")
    print(f"   المعرفة {k}% | الاستدلال {r}% | التطبيق {a}%")
    if weak:
        print("   مفاهيم ضعيفة (جدولة مستقلة لكل منها):")
        for c in weak:
            print(f"   • {c['title']} — إتقان {round(sum(v for v in c['mastery'].values() if v is not None)/3)}% — {'⚠️ سوء فهم مسجل' if c['misconception_flags'] else 'بحاجة تعزيز'}")
    print(f"   رُتبت {len(created)} مراجعة متباعدة (اليوم/غدًا ثم 3/7/14/30 يومًا) — ستظهر في بريف الصباح.")


def cmd_due():
    st, S = _load()
    items = [x for x in S["learning_reviews"]
             if x["status"] in ("SCHEDULED", "DUE", "PRESENTED") and dt.date.fromisoformat(str(x["due_date"])[:10]) <= TODAY]
    if not items:
        print("لا مراجعات مستحقة اليوم ✅")
        return
    for x in items:
        print(f"{x['review_id']} [{x['status']}] {x['concept_title']} — {x['est_minutes']} دقائق (استحقاق {x['due_date']})")


def _review(S, rid):
    return next((x for x in S["learning_reviews"] if x["review_id"] == rid), None)


def cmd_present(rid):
    st, S = _load()
    x = _review(S, rid)
    if not x or x["status"] not in ("SCHEDULED", "DUE"):
        sys.exit("❌ المراجعة غير متاحة")
    x["status"], x["presented_at"] = "PRESENTED", TODAY.isoformat()
    st.commit(S, "review_presented", review=rid)
    log_event("REVIEW_PRESENTED", review=rid)
    print(f"📖 {rid} — {x['concept_title']}: اعرض سؤال الاسترجاع الآن (بصيغة prompts/personal-training.md)")


def cmd_answer(rid, score):
    st, S = _load()
    x = _review(S, rid)
    if not x or x["status"] not in ("DUE", "PRESENTED", "SCHEDULED"):
        sys.exit("❌ لا يمكن تسجيل إجابة على هذه المراجعة")
    score = max(0, min(100, int(score)))
    c = next((y for y in S["learning_concepts"] if y["concept_id"] == x["concept_id"]), None)
    if c:
        for key in ("knowledge", "reasoning", "application"):
            c["mastery"][key] = _ema(c["mastery"][key], score)
        c["last_tested"], c["last_score"] = TODAY.isoformat(), score
        c["history"].append({"date": TODAY.isoformat(), "score": score, "review": rid})
        if score < 70:
            c["misconception_flags"].append(f"review@{TODAY}: {score}")
    x["status"], x["answered_at"] = "SCORED", TODAY.isoformat()
    if score >= 70:
        x["interval_idx"] += 1
        if x["interval_idx"] >= len(INTERVALS):
            x["status"] = "COMPLETED"
            nxt = "اكتمل السلم — المفهوم مُتقن ✅"
            if c:
                c["next_review"] = None
        else:
            nxt_days = INTERVALS[x["interval_idx"]]
            x["status"], x["est_minutes"] = "SCHEDULED", 5
            x["due_date"] = (TODAY + dt.timedelta(days=nxt_days)).isoformat()
            nxt = f"المراجعة التالية بعد {nxt_days} أيام (5 دقائق)"
            if c:
                c["next_review"] = x["due_date"]
    else:
        x["interval_idx"] = 0
        x["status"], x["est_minutes"] = "SCHEDULED", 7
        x["due_date"] = (TODAY + dt.timedelta(days=1)).isoformat()
        nxt = "⚠️ إعادة شرح + جدولة من جديد غدًا"
        if c:
            c["next_review"] = x["due_date"]
    st.commit(S, "review_scored", review=rid, score=score)
    log_event("REVIEW_SCORED", review=rid, score=score)
    print(f"✅ {rid} — {score}% | {nxt}")


def cmd_mastery():
    st, S = _load()
    if not S["learning_concepts"]:
        print("خريطة الإتقان فارغة.")
        return
    print(f"{'المفهوم':<38} {'معرفة':>6} {'استدلال':>8} {'تطبيق':>6} {'سوء فهم':>8} {'المراجعة':>12}")
    for c in S["learning_concepts"]:
        m = c["mastery"]
        avg_n = sum(1 for v in (m["knowledge"], m["reasoning"], m["application"]) if v is not None)
        if not avg_n:
            continue
        flag = "⚠️" if c["misconception_flags"] else "—"
        print(f"{c['title'][:36]:<38} {m['knowledge'] or 0:>5}% {m['reasoning'] or 0:>7}% "
              f"{m['application'] or 0:>5}% {flag:>8} {str(c['next_review'] or '—'):>12}")


def cmd_outline(pid):
    """يولّد الهيكل المنهجي (ILPC — Bob Pike: EAT + CPR + 90/20/8) لكل جزء — يملؤه التدريس الحي."""
    st, S = _load()
    p = _plan(S, pid)
    if not p:
        sys.exit(f"❌ لا توجد خطة {pid}")
    print(f"🗺️ هيكل مادة ILPC — {p['plan_id']} «{p['title']}»")
    print(f"   جلسة ≤{p.get('session_minutes', 45)} دقيقة (90 حدًا أقصى) | تدريس ≤20 دقيقة لكل جزء | تفاعل كل ~8 دقائق | التقييم: خريطة الإتقان + سلم 1/3/7/14/30\n")
    for sec in p["sections"]:
        mins = 20
        print(f"▸ الجزء {sec['part']} — {sec['title']} ({mins} دقيقة)")
        print(f"   🎯 الهدف القابل للقياس: {sec.get('objective') or '(يُعرَّف قبل التدريس — ماذا سيستطيع فعله بعدها؟)'}")
        print("   🧪 E — التجربة أولًا: حالة/بيانات من واقع عمله (وليس شرحًا نظريًا)")
        print("   🔎 A — الوعي: سؤالان عن ما حدث للتو")
        print("   📖 T — النظرية: 3–5 نقاط مركزة تفسر التجربة")
        print("   🙋 المشاركة: سؤال استرجاع + سؤال تطبيقي (تُسجل درجته في: score " + pid + f" {sec['part']} N)")
        print("   🪞 تأمل (دقيقة واحدة): ما الذي يذكّرك به من عملك؟")
        print("   🔁 إعادة الزيارة (اللقاء التالي — المتعلم من يراجع): لخّص بكلماتك الجزء السابق")
        print()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "plan":
            cmd_plan(sys.argv[2], int(_val("parts", 6)), _val("goal"), _val("domain"), _val("titles"))
        elif cmd == "start":
            cmd_start(sys.argv[2])
        elif cmd == "score":
            cmd_score(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        elif cmd == "final":
            cmd_final(sys.argv[2])
        elif cmd == "due":
            cmd_due()
        elif cmd == "present":
            cmd_present(sys.argv[2])
        elif cmd == "answer":
            cmd_answer(sys.argv[2], int(sys.argv[3]))
        elif cmd == "mastery":
            cmd_mastery()
        elif cmd == "outline":
            cmd_outline(sys.argv[2])
        else:
            print(__doc__)
    except SystemExit as e:
        print(e)

# -*- coding: utf-8 -*-
"""
عقل المدير الشخصي — Level 2 (Executive Personal Manager).

يعمل بوضعين:
  1) حتمي (افتراضي، بلا أي API): تصنيف النية عربي/إنجليزي + ردود مبنية على
     البروتوكولات المستخرجة من الشيت (مصفوفة الإرشادات + سرعة القرار +
     نقاط الضعف + العبارات + بروتوكول الطاقة).
  2) نموذج لغوي اختياري: إن ضُبط LLM_BASE_URL/LLM_MODEL تُصاغ الردود عبر
     النموذج مع نفس سياق البروتوكولات، وبرجوع تلقائي عند الفشل.

مستوى الاستقلالية = L2: تنفيذ داخلي قابل للعكس (مهام/قرارات/سجلات) + تقرير.
لا أثر خارجي أبدًا (رسائل، مدفوعات، نشر) — اقتراح فقط.
"""
from __future__ import annotations

import re

from . import llm
from .identity import PROFILE, style_prompt
from .protocols import (
    AGENT_MATRIX, CALM_TECHNIQUES, CORE_PRINCIPLE, DECISION_PROTOCOL,
    EXHAUSTION_PROTOCOL, WEAKNESSES, find_phrase, find_weakness,
)
from .state import get_store, now, parse_date

# ─────────────────────────────────────────────────────────────────────────────
# تصنيف النية
# ─────────────────────────────────────────────────────────────────────────────
INTENTS = [
    ("brief",      ["بريف", "صباح الخير", "صباحا", "البريف", "ملخص اليوم", "brief", "morning", "good morning", "أولويات"]),
    ("task_add",   ["مهمة جديدة", "أضف مهمة", "سجل مهمة", "add task", "new task", "مهمة:", "مهمة :", "task:", "أضف ", "سجل ", "خل مهمة"]),
    ("task_list",  ["مهامي", "المهام", "قائمة المهام", "tasks", "my tasks", "وش عندي", "ماذا عندي"]),
    ("task_done",  ["أنجزت", "خلصت", "تمت", "أكملت", "done", "completed", "أنهيت"]),
    ("decision",   ["قرار", "أحسم", "محتار", "أتردد", "decision", "decide", "أختار", "خيارين", "وش اختار"]),
    ("weakness",   ["نقطة ضعف", "ضعفي", "أطور نفسي", "weakness", "طوري نفسي", "كمالية", "تسويف", "شلل"]),
    ("review",     ["مراجعة", "أسبوعية", "review", "weekly", "حاسبني", "مساءلة"]),
    ("waiting",    ["انتظار", "بانتظار", "waiting", "أنتظر", "متابعة الخارج"]),
    ("energy",     ["طاقتي", "طاقة", "إرهاق", "متعب", "مرهق", "energy", "tired", "exhausted", "منهك"]),
    ("calm",       ["تأمل", "تنفس", "هدوء", "استرخاء", "calm", "breathe", "meditat", "ريلاكس"]),
    ("phrase",     ["عبارة", "صياغة", "رد جاهز", "phrase", "كيف أرد", "وش أقول", "كيف اقول"]),
    ("idea",       ["فكرة", "مبادرة", "مشروع جديد", "idea", "new project", "خطرت لي"]),
    ("status",     ["حالة النظام", "status", "وضعك", "تشخيص", "diag"]),
    ("help",       ["مساعدة", "help", "وش تسوي", "ماذا تستطيع", "أوامر"]),
]


def classify(text: str) -> str:
    t = (text or "").strip().lower()
    best, best_score = "consult", 0
    for intent, kws in INTENTS:
        score = sum(1 for kw in kws if kw in t)
        if score > best_score:
            best, best_score = intent, score
    return best


# ─────────────────────────────────────────────────────────────────────────────
# بناة الردود الحتمية
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_task(t: dict) -> str:
    due = f" · استحقاق {t['due']}" if t.get("due") else ""
    return f"• [{t['id']}] {t['title']}{due} — الخطوة: {t.get('next_step') or 'حدد أول خطوة'}"


def reply_brief() -> str:
    st = get_store()
    b = st.brief()
    lines = ["صباح الخير ☀️ — بريف مركز (طاقتك محفوظة للعمل العميق):", ""]
    if b["priorities"]:
        lines.append("🎯 أولويات اليوم (اثنتان فقط):")
        lines += [_fmt_task(t) for t in b["priorities"]]
    else:
        lines.append("🎯 لا مهام مفتوحة — سجّل أولويتي اليوم بأمر «مهمة: ...»")
    lines.append("")
    if b["pending_decision"]:
        d = b["pending_decision"]
        lines.append(f"⚖️ قرار واحد معلق: «{d['title']}» — قابل للعكس: "
                     f"{'نعم' if d.get('reversible') else 'لا'} · مهلة الحسم: {d.get('deadline', '')[:16].replace('T', ' ')}")
        lines.append("   قاعدة 70%: المعلومات المتوفرة كافية غالبًا؛ نحسمه اليوم؟ (أ) نعم نحسم الآن (ب) أمدد المهلة ليوم واحد فقط")
    else:
        lines.append("⚖️ لا قرارات معلقة — ممتاز.")
    warns = []
    if b["tasks_overdue"]:
        warns.append(f"{b['tasks_overdue']} مهمة متأخرة")
    if b["waiting_stale"]:
        warns.append(f"{b['waiting_stale']} عنصر انتظار تجاوز 14 يومًا")
    if b["last_energy"] and b["last_energy"].get("energy", 10) <= 4:
        warns.append("طاقتك آخر تسجيل منخفضة — راجع بروتوكول الإرهاق")
    if warns:
        lines.append("")
        lines.append("⚠️ " + " · ".join(warns))
    if b["last_energy"]:
        lines.append("")
        lines.append(f"🔋 آخر تسجيل طاقة: {b['last_energy']['energy']}/10")
    lines.append("")
    lines.append("ما خطوتك الأولى الآن؟")
    return "\n".join(lines)


def reply_task_add(text: str) -> tuple[str, list[dict]]:
    st = get_store()
    # «مهمة: العنوان قبل 2026-10-10» أو «أضف مهمة ...»
    m = re.search(r"(?:مهمة[:\s]*|add task[:\s]*|new task[:\s]*)(.+)", text, re.I)
    raw = m.group(1).strip() if m else text.strip()
    due = None
    dm = re.search(r"(?:قبل|by|due)\s+([\d/\-]+|اليوم|غدا|غدًا|بعد غد)", raw, re.I)
    if dm:
        due = parse_date(dm.group(1))
        if due:
            due = due.isoformat()
            raw = (raw[:dm.start()] + raw[dm.end():]).strip(" ،,")
    if not raw:
        return "اكتب المهمة بهذه الصيغة: «مهمة: عنوان المهمة قبل 2026-10-10»", []
    task = st.add_task(title=raw, due=due)
    return (
        f"تم تسجيل المهمة [{task['id']}] «{task['title']}»"
        + (f" — استحقاق {task['due']}" if task["due"] else "")
        + ".\nالخطوة التالية المقترحة: حدد أول إجراء مادي خلال 48 ساعة. ما هو؟"
    ), [task]


def reply_task_list() -> str:
    st = get_store()
    open_t = st.tasks_open()
    if not open_t:
        return "لا مهام مفتوحة حاليًا. أضف واحدة: «مهمة: العنوان قبل التاريخ»"
    overdue = st.tasks_overdue()
    lines = [f"المهام المفتوحة: {len(open_t)} (منها {len(overdue)} متأخرة):", ""]
    lines += [_fmt_task(t) for t in open_t[:10]]
    if len(open_t) > 10:
        lines.append(f"... و{len(open_t) - 10} أخرى")
    lines.append("")
    lines.append("لقاعدة التركيز: أنجز المتأخرة الحرجة أولًا، وأغلق أو فوّض اثنتين منخفضة الأثر هذا الأسبوع.")
    return "\n".join(lines)


def reply_task_done(text: str) -> tuple[str, list[dict]]:
    st = get_store()
    # ابحث عن رقم المهمة أو عنوانها
    m = re.search(r"\bT-[A-Z0-9]{4,8}\b", text, re.I)
    if m:
        t = st.complete_task(m.group(0))
        if t:
            return f"أُغلقت [{t['id']}] «{t['title']}» ✓ — هل لديك دليل إنجاز (رابط/ملف/رقم)؟ توثيقه يبني ملف إنجازاتك.", [t]
    # انزع كلمات الإنجاز ثم طابق العنوان (العنوان ⊂ النص أو النص ⊂ العنوان)
    cleaned = re.sub(
        r"أنجزت|أنهيت|أكملت|خلصت|تمت|تمّت|done|completed|i did|finished",
        "", text, flags=re.I,
    ).strip(" ،,.؟!")
    for t in st.tasks_open():
        title = (t.get("title") or "").strip()
        if title and (title in cleaned or cleaned in title):
            done = st.complete_task(t["id"])
            return f"أُغلقت [{done['id']}] «{done['title']}» ✓ — ما الدليل العملي على الإنجاز؟", [done]
    return "لم أجد المهمة. أرسل رقمها (مثل T-1A2B3C) أو جزءًا من عنوانها مع كلمة «أنجزت».", []


def reply_decision(text: str) -> tuple[str, list[dict]]:
    st = get_store()
    # هل هذا حسم لقرار قائم؟
    for d in st.decisions_pending():
        if d["title"].strip() and d["title"].strip().lower() in text.lower():
            st.close_decision(d["id"])
            return (
                f"تم تثبيت القرار «{d['title']}» ✓ (قاعدة الـ 48 ساعة):\n"
                "ما الإجراء المادي الأول الذي ستنفذه خلال 48 ساعة؟"
            ), [d]
    # استشارة قرار جديد
    m = re.search(r"(?:قرار[:\s]*|أحسم[:\s]*|decision[:\s]*)(.+)", text, re.I)
    title = m.group(1).strip() if m else text.strip()
    if not title:
        title = "قرار غير معنون"
    dec = st.add_decision(title=title, reversible=True, deadline_hours=24)
    stage = DECISION_PROTOCOL[0]
    return (
        f"سجلنا القرار «{title}» [{dec['id']}] — مهلة الحسم 24 ساعة (بروتوكول {stage['name']}).\n"
        "أمامك خياران رئيسيان فقط — قاعدة البديلين (أ/ب). اكتبهما وسأرجّح معك بثلاثة معايير:\n"
        "1) الأثر المالي  2) الجهد والوقت  3) سهولة العودة.\n"
        "وتذكير: نسبة يقين 70% كافية تمامًا لقرار قابل للعكس — التعلم يبدأ بعد الإطلاق."
    ), [dec]


def reply_weakness(text: str) -> str:
    w = find_weakness(text)
    if not w:
        names = "، ".join(x["name"] for x in WEAKNESSES[:8])
        return (
            "أستطيع تدريبك على 29 نقطة ضعف موثقة من مصفوفة التطوير.\n"
            f"منها: {names}...\n"
            "اذكر ما يزعجك اليوم (مثل: «أعاني من الكمالية») وسأعطيك التعليمة البديلة والحد الأدنى الأسبوعي ومؤشر النجاح."
        )
    return (
        f"📌 نقطة الضعف: {w['name']}\n"
        f"• المحفّز المعتاد: {w['trigger']}\n"
        f"• التعليمة البديلة: {w['instruction']}\n"
        f"• السلوك المطلوب: {w['behavior']} (الحد الأدنى الأسبوعي: {w['weekly_min']})\n"
        f"• مؤشر النجاح: {w['metric']} ({w['cadence']})\n\n"
        "ما أصغر خطوة تنفذها الآن خلال 5 دقائق؟"
    )


def reply_review() -> tuple[str, list[dict]]:
    st = get_store()
    s = st.weekly_stats()
    energy = f"{s['energy_avg']:.1f}/10" if s["energy_avg"] is not None else "لا تسجيلات"
    review = {
        "tasks_completed": s["tasks_completed"],
        "decisions_closed": s["decisions_closed"],
        "tasks_overdue": s["tasks_overdue"],
        "energy_avg": s["energy_avg"],
        "verdict": "",
    }
    if s["decisions_closed"] == 0 and s["decisions_pending"] > 0:
        verdict = "قرارات مؤجلة بلا معطى جديد — الهدف الأسبوع القادم: صفر."
    elif s["decisions_closed"] >= 3:
        verdict = "وتيرة حسم قوية — حافظ عليها."
    else:
        verdict = "حسم قرارين على الأقل الأسبوع القادم."
    review["verdict"] = verdict
    st.save_review(review)
    reply = (
        "📊 المراجعة الأسبوعية (قياس العملية لا النتيجة فقط):\n"
        f"• مهام أُنجزت هذا الأسبوع: {s['tasks_completed']}\n"
        f"• قرارات حُسمت: {s['decisions_closed']} (معلقة الآن: {s['decisions_pending']})\n"
        f"• مهام متأخرة: {s['tasks_overdue']} · مفتوحة: {s['tasks_open']}\n"
        f"• متوسط الطاقة: {energy}\n\n"
        f"الحكم: {verdict}\n"
        "قرار الأسبوع القادم — اختر واحدًا: (أ) إغلاق أكبر عدد من الحلقات المفتوحة (ب) حسم أقدم قرار معلق."
    )
    return reply, [review]


def reply_waiting() -> str:
    st = get_store()
    open_w, stale = st.waiting_open()
    if not open_w:
        return "لا عناصر في الانتظار — كل الحلقات مغلقة. ممتاز."
    lines = [f"الانتظار المفتوح: {len(open_w)} عنصرًا:"]
    lines += [f"• [{w['id']}] {w['item']} — بانتظار {w['waiting_on']} (منذ {w['requested']})" for w in open_w[:8]]
    if stale:
        lines.append("")
        lines.append("⚠️ تجاوز 14 يومًا (يُرفع كقضية قرار): " + "، ".join(w["item"] for w in stale[:3]))
        lines.append("خياران: (أ) متابعة حاسمة اليوم (ب) إغلاق العنصر والاستغناء")
    return "\n".join(lines)


def reply_energy(text: str) -> tuple[str, list[dict]]:
    st = get_store()
    m = re.search(r"\b(\d|10)\s*/\s*10\b|\b(\d|10)\b", text)
    level = None
    if m:
        try:
            level = int(m.group(1) or m.group(2))
            if not 1 <= level <= 10:
                level = None
        except ValueError:
            level = None
    if level is None:
        return (
            "سجّل طاقتك من 1 إلى 10 (مثال: «طاقتي 4»).\n"
            "الطاقة مورد تشغيلي لا مجرد شعور — قياسها يحدد سقف التزامات اليوم."
        ), []
    st.log_energy(level)
    if level >= 8:
        return (
            f"طاقتك {level}/10 — ممتازة. استثمرها في العمل العميق على أهم مهمة، وأغلق اليوم أهم قرار معلق."
        ), []
    if level >= 5:
        return (
            f"طاقتك {level}/10 — متوسطة. خياران: (أ) مهمة واحدة عميقة فقط اليوم (ب) مهام قصيرة متكررة. "
            "أوصي بـ (أ) — الأثر أعلى."
        ), []
    return (
        f"طاقتك {level}/10 — منخفضة. بروتوكول الإرهاق يفعّل الآن:\n"
        + "\n".join(f"• {x}" for x in EXHAUSTION_PROTOCOL[:4])
        + f"\n\nتقنية مقترحة فورًا: {CALM_TECHNIQUES[0]['name']} — {CALM_TECHNIQUES[0]['how']}"
    ), []


def reply_calm(text: str) -> str:
    matched = None
    t = text.lower()
    for tech in CALM_TECHNIQUES:
        if tech["name"].lower() in t:
            matched = tech
            break
    if not matched:
        import random
        matched = random.choice(CALM_TECHNIQUES)
    return (
        f"🧘 {matched['name']} — متى: {matched['when']}\n"
        f"كيف: {matched['how']}\n\n"
        "دقيقتان الآن تكفيان. أي تقنية أخرى؟ اكتب اسمها (مثل Box Breathing أو 4-7-8)."
    )


def reply_phrase(text: str) -> str:
    p = find_phrase(text)
    if not p:
        return (
            "اذكر الموقف (مثل: «طلب مساعدة مفاجئ» أو «مواجهة تأخير») وسأعطيك العبارة الجاهزة.\n"
            "لدي 28 موقفًا موثقًا في مكتبة العبارات التوجيهية."
        )
    return (
        f"💬 موقف: {p['situation']} (الهدف: {p['goal']})\n"
        f"العبارة: «{p['phrase']}»\n"
        f"تجنّب: {p['avoid']}"
    )


def reply_idea(text: str) -> tuple[str, list[dict]]:
    st = get_store()
    m = re.search(r"(?:فكرة[:\s]*|idea[:\s]*|مشروع جديد[:\s]*)(.+)", text, re.I)
    idea = m.group(1).strip() if m else text.strip()
    p = st.add_possibility(idea)
    return (
        f"فكرة واعدة — حُفظت في صندوق الاحتمالات [{p['id']}] حتى لا تشتت تركيزنا الحالي (قاعدة M6).\n"
        "ستُقيَّم في المراجعة الأسبوعية بشرط واحد: ما المشكلة التي تحلها؟ لا نبدأ مشروعًا قبل إغلاق المفتوح."
    ), [p]


def reply_status() -> str:
    st = get_store()
    s = st.weekly_stats()
    l = llm.status()
    return (
        "🩺 حالة المدير الشخصي — Level 2:\n"
        f"• وضع العقل: {l['mode']}" + (f" ({l['model']})" if l["model"] else "") + "\n"
        f"• مهام مفتوحة: {s['tasks_open']} · متأخرة: {s['tasks_overdue']}\n"
        f"• قرارات معلقة: {s['decisions_pending']}\n"
        "• الذاكرة: ملف JSON محلي + 7 نسخ دوّارة (لا سحابة ولا مفاتيح)\n"
        "• مستوى الاستقلالية: L2 — داخلي فقط + تقرير؛ الخارج اقتراح"
    )


def reply_help() -> str:
    return (
        "أنا مديرك الشخصي التنفيذي (Level 2). أتكلم معك وأستشيرك حسب بروتوكولاتك الموثقة. جرّب:\n"
        "• «بريف» — أولويتان + قرار واحد\n"
        "• «مهمة: العنوان قبل 2026-10-10» — تسجيل مهمة\n"
        "• «أنجزت T-XXXXXX» أو «أنجزت عنوان المهمة»\n"
        "• «قرار: ...» — استشارة حسم بخيارين وقاعدة 70%\n"
        "• «أعاني من الكمالية/التسويف/...» — بروتوكول نقطة الضعف\n"
        "• «طاقتي 4» — تسجيل الطاقة وتفعيل بروتوكول الإرهاق عند الحاجة\n"
        "• «تأمل» — تقنية هدوء فورية\n"
        "• «عبارة لطلب مساعدة مفاجئ» — رد جاهز\n"
        "• «فكرة: ...» — حفظ في صندوق الاحتمالات\n"
        "• «مراجعة» — المراجعة الأسبوعية · «حالة النظام»"
    )


# ─────────────────────────────────────────────────────────────────────────────
# نقطة الدخول
# ─────────────────────────────────────────────────────────────────────────────

def _deterministic_reply(intent: str, text: str) -> tuple[str, list[dict]]:
    """يرجع (الرد، الأثر الداخلي المنفذ) — كل الأثر داخلي قابل للعكس."""
    if intent == "brief":
        return reply_brief(), []
    if intent == "task_add":
        return reply_task_add(text)
    if intent == "task_list":
        return reply_task_list(), []
    if intent == "task_done":
        return reply_task_done(text)
    if intent == "decision":
        return reply_decision(text)
    if intent == "weakness":
        return reply_weakness(text), []
    if intent == "review":
        return reply_review()
    if intent == "waiting":
        return reply_waiting(), []
    if intent == "energy":
        return reply_energy(text)
    if intent == "calm":
        return reply_calm(text), []
    if intent == "phrase":
        return reply_phrase(text), []
    if intent == "idea":
        return reply_idea(text)
    if intent == "status":
        return reply_status(), []
    if intent == "help":
        return reply_help(), []
    # consult — سؤال عام
    b = get_store().brief()
    core = (
        "سؤالك خارج البروتوكولات الجاهزة، وسأكون صريحًا: لا أخمّن (قاعدة M4).\n"
        "خياران للانتقال للأثر: (أ) صُغ سؤالك كقرار: «قرار: ...» فأعطيك استشارة خيارين كاملة "
        "(ب) اذكر المجال (مهمة/طاقة/نقطة ضعف/انتظار) فأفعّل البروتوكول المناسب.\n"
    )
    if b["pending_decision"]:
        core += f"\nوتذكير: قرار «{b['pending_decision']['title']}» ما زال معلقًا — 70% يقين كافية."
    return core, []


def _system_prompt() -> str:
    st = get_store()
    b = st.brief()
    matrix = "\n".join(f"- {m['rule']}: {m['required']}" for m in AGENT_MATRIX[:6])
    ctx = (
        f"التاريخ: {b['date']}\n"
        f"مهام مفتوحة: {b['tasks_open']} (متأخرة: {b['tasks_overdue']}) · قرارات معلقة: {b['decisions_pending']}\n"
        f"أولويات اليوم: {'؛ '.join(t['title'] for t in b['priorities']) or 'لا شيء مسجل'}\n"
    )
    return (
        "أنت «المدير الشخصي التنفيذي» لعبدالرحمن — مستوى استقلالية L2 (تنفيذ داخلي قابل للعكس + تقرير؛ "
        "لا أثر خارجي أبدًا).\n"
        f"المبدأ الجوهري: «{CORE_PRINCIPLE}».\n"
        f"{style_prompt()}\n\n"
        f"قواعد ملزمة:\n{matrix}\n"
        "- بروتوكول القرار: خياران فقط (أ/ب) + توصية صريحة + 70% يقين للقرارات القابلة للعكس + مهلة 24 ساعة + إجراء مادي خلال 48 ساعة.\n"
        "- بعد أي حسم اسأل عن الإجراء المادي الأول خلال 48 ساعة.\n\n"
        f"سياق الحالة الحالية:\n{ctx}\n"
        "أجب بالعربية (أو بنفس لغة المستخدم)، بإيجاز مركز، واختم بسؤال حاسم واحد."
    )


def handle(text: str, session_id: str | None = None, channel: str = "web") -> dict:
    """المعالج الرئيسي: يرجع {reply, intent, actions, mode}."""
    st = get_store()
    text = (text or "").strip()
    if not text:
        return {"reply": "أنا معك — تحدث أو اكتب.", "intent": "empty", "actions": [], "mode": "offline"}
    if not session_id:
        session_id = st.start_session(channel)

    intent = classify(text)
    deterministic, actions = _deterministic_reply(intent, text)

    reply, mode = deterministic, "offline"
    if llm.enabled():
        history = []
        for s in st.snapshot()["sessions"]:
            if s["id"] == session_id:
                history = s["exchanges"]
                break
        enhanced = llm.chat(_system_prompt(), text, history)
        if enhanced and enhanced.strip():
            reply, mode = enhanced.strip(), "llm"
            # الأثر الداخلي نُفذ حتميًا فوق — النموذج يصوغ فقط

    st.add_exchange(session_id, text, reply, intent)
    return {
        "reply": reply,
        "intent": intent,
        "actions": [
            (a.get("id") or "") + " · " + (a.get("title") or a.get("idea") or a.get("item") or "")
            for a in actions
        ],
        "mode": mode,
        "session": session_id,
    }

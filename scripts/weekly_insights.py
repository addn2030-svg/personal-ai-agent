# -*- coding: utf-8 -*-
"""مهارة التحقق الأسبوعي: تحلل سجل محادثات الوكيل في Supabase وتستخلص الدروس.

المصدر: agent_conversations (2,300+ صف من أسئلة عبدالرحمن وردود البوت منذ أغسطس).
المخرج: تقرير من 10-15 سطرًا — أكثر ما تكرر، مواضيع، أوقات الذروة، اقتراحان ملموسان.

الاستخدام:
  python scripts/weekly_insights.py            # آخر 30 يومًا
  python scripts/weekly_insights.py --days 90  # نطاق أوسع
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# ---- تحميل المفاتيح: Railway vars إن وجدت، وإلا من متغيرات البيئة ----
VARS_CACHE = Path(os.environ.get("TMPDIR") or Path.home()) / "rvars.json"


def _load_env():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    # مسارات مفاتيح مخزنة (rvars.json من جلسة العمل) — اقرأها قبل المتغيرات
    for p in (Path(os.environ.get("TMPDIR") or "") / "rvars.json",
              Path.home() / "AppData/Local/hermes/cache/scratch/rvars.json"):
        try:
            if p.exists():
                v = json.loads(p.read_text(encoding="utf-8"))
                return str(v["SUPABASE_URL"]).rstrip("/"), str(v["SUPABASE_SERVICE_ROLE_KEY"])
        except Exception:  # noqa: BLE001
            pass
    import subprocess
    try:
        out = subprocess.run(["railway", "variables", "--service", "personal-ai-agent", "--json"],
                             capture_output=True, text=True, timeout=60, cwd=str(Path(__file__).resolve().parents[1])).stdout
        v = json.loads(out)
        return str(v["SUPABASE_URL"]).rstrip("/"), str(v["SUPABASE_SERVICE_ROLE_KEY"])
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"لا أستطيع تحميل مفاتيح Supabase: {exc}")


def fetch_conversations(url: str, key: str, days: int) -> list[dict]:
    since = (dt.datetime.now(dt.timezone(dt.timedelta(hours=3)))
             - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    rows, offset = [], 0
    while True:
        q = (f"agent_conversations?select=question,answer,occurred_at,input_tokens,output_tokens,status"
             f"&occurred_at=gte.{since}&order=occurred_at.asc&limit=1000&offset={offset}")
        req = urllib.request.Request(f"{url}/rest/v1/{q}",
                                     headers={"apikey": key, "Authorization": "Bearer " + key})
        batch = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if not batch:
            break
        rows.extend(batch)
        offset += 1000
        if len(batch) < 1000:
            break
    return rows


STOP_AR = set("في من على عن مع هذا هذه ذلك الذي التي كان كنت أنا أن هو هي ما لا لم ثم كل بين إلى أو كما هناك عند قد كما قد حتى إذا لكن حتى متى كيف ماذا لماذا أين نعم أيضا أيضاً الآن اليوم أم بأن إن لن به له لها بها منه منها اليك لك لي لي نحن هم هن انا انت أنت".split())
LATIN = re.compile(r"[a-zA-Z]")
AR = re.compile(r"[\u0600-\u06FF]")


def top_topics(questions: list[str], n: int = 8) -> list[tuple[str, int]]:
    """المواضيع الأكثر تكرارًا من أفعال/كلمات دلالية في الأسئلة."""
    freq: collections.Counter = collections.Counter()
    KEY = {"تقرير", "قراءة", "مكتبة", "بريف", "مهام", "مهمة", "مراجعة", "طب",
           "علاج", "علاجي", "مريض", "مريض", "عيادة", "سريري", "اعتماد",
           "وضع", "بناء", "وكيل", "نظام", "ورشة", "تدريب", "تطوير", "نشر",
           "تفريغ", "صوت", "فيديو", "قناة", "محتوى", "تصوير", "مالي",
           "ميزانية", "دين", "جدول", "تقويم", "تنبيه", "تيليجرام"}
    for q in questions:
        words = re.findall(r"[\u0600-\u06FFa-zA-Z_]{3,}", q)
        for w in words:
            if w in KEY or (w not in STOP_AR and len(w) >= 4 and w in KEY):
                freq[w] += 1
    return freq.most_common(n)


def peak_hours(times: list[str]) -> dict[int, int]:
    hours: collections.Counter = collections.Counter()
    for t in times:
        try:
            h = int(str(t)[11:13])
            hours[h] += 1
        except (ValueError, IndexError):
            continue
    return hours


def build_report(rows: list[dict], days: int) -> str:
    if not rows:
        return f"لا محادثات في آخر {days} يومًا — الوكيل صامت."
    questions = [r["question"] or "" for r in rows]
    answers = [r["answer"] or "" for r in rows]
    total_in = sum(r.get("input_tokens") or 0 for r in rows)
    total_out = sum(r.get("output_tokens") or 0 for r in rows)
    # كم سؤالًا أجاب عنه البوت بالعربية؟
    ar_answers = sum(1 for a in answers if AR.search(a))
    en_answers = sum(1 for a in answers if LATIN.search(a) and not AR.search(a))
    hour_hist = peak_hours([r["occurred_at"] or "" for r in rows])
    top_hours = ", ".join(f"{h:02d}:00 ({c})" for h, c in hour_hist.most_common(3))
    topics = top_topics(questions)
    # متوسط زمن الاستجابة من status
    err = sum(1 for r in rows if str(r.get("status", "")).upper() == "ERROR")
    lines = [
        f"تقرير استخلاص الدروس — آخر {days} يومًا",
        f"محادثات: {len(rows)} | توكنات: {total_in:,} دخل + {total_out:,} خرج | أخطاء: {err}",
        f"لغة الردود: عربي {ar_answers} / إنجليزي {en_answers}",
        f"أوقات ذروتك: {top_hours}",
        "أكثر ما تكرر في أسئلتك:",
    ]
    for word, c in topics[:8]:
        lines.append(f"  • {word} — {c} مرة")
    # اقتراحان ملموسان من البيانات نفسها
    s = []
    if en_answers > ar_answers * 0.3:
        s.append(f"ثلث ردود البوت إنجليزية تقريبًا ({en_answers}/{len(rows)}) — ربّط «أجب بلغة السؤال» بقوة أكبر.")
    if err:
        s.append(f"أخطاء: {err} — راجع آخرها في agent_status_log.")
    if hour_hist:
        peak = hour_hist.most_common(1)[0][0]
        s.append(f"ذروة استخدامك {peak:02d}:00 — أزح البريف الصباحي إلى قبلها بعشر دقائق ليصلك جاهزًا.")
    if topics:
        s.append(f"أسئلتك المتكررة أعلاه تصلح مهارات ذاكرة إجرائية — ابدأ بأعلاها («{topics[0][0]}»).")
    lines.append("")
    lines.append("اقتراحات مبنية على بياناتك:")
    seen = set()
    for x in s:
        if x not in seen:
            lines.append(f"  - {x}")
            seen.add(x)
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(prog="weekly_insights")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    url, key = _load_env()
    rows = fetch_conversations(url, key, args.days)
    print(build_report(rows, args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
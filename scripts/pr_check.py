# -*- coding: utf-8 -*-
"""فحص جودة الـ Pull Request قبل الدمج (بوابة PR المحلية).

فحوصات:
  1. حجم الـ diff: تحذير إن تجاوز الحد (افتراضيًا 500 سطر مضاف).
  2. ملفات حساسة: هل يعدّل PR ملفات يجب ألا تُلمس بسهولة (env, credentials,
     migrations قديمة).
  3. حذف خارج النطاق: نسبة حذف مرتفعة (افتراضيًا >40% من الـ diff) تستدعي
     مراجعة بشرية — مثلًا مولّد كود حذف كودًا لم يُطلب منه.
  4. أسرار: نفس أنماط حرس الأسرار (عبر secret_guard).

الاستخدام:
  python scripts/pr_check.py                 # فحص آخر كوميت غير مرفوع
  python scripts/pr_check.py --base main --head HEAD~2   # فحص نطاق كوميتات

يعيد exit 0 = يعمل الدمج، exit 1 = أوقف وراجع.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secret_guard import PATTERNS, PLACEHOLDER  # noqa: E402

BASE_DIR = Path(__file__).resolve().parents[1]

# ملفات لا يجوز تعديلها في PR عادي (تستدعي مراجعة صريحة)
# ملاحظة: ci.yml نفسها مسموحة (وإلا فكيف نطور البوابات؟) — البوابات الأخرى تحرسها.
PROTECTED_FILES = {
    ".env", ".env.local", ".env.production",
    "connectors/clinical_sheet.py",       # مسار السريري المحمي
    "supabase/01_state_snapshots.sql",    # migrations قديمة — لا تعديل رجعي
    "supabase/02_tasks_mirror.sql",
    "supabase/03_operational_mirrors.sql",
    "Dockerfile",
}

MAX_ADDED_LINES = 500       # حد التنبيه للحجم
MAX_DELETE_RATIO = 0.40     # أكثر من 40% حذف = مراجعة


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(BASE_DIR)] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def diff_stat(base: str, head: str) -> dict:
    out = git("diff", "--no-color", "--numstat", base, head)
    added = deleted = 0
    touched: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            a, d, path = parts
            if a != "-":
                added += int(a)
            if d != "-":
                deleted += int(d)
            touched.append(path)
    return {"added": added, "deleted": deleted, "touched": touched}


def diff_text(base: str, head: str) -> str:
    return git("diff", "--no-color", "-U0", base, head)


def check(base: str, head: str) -> list[str]:
    problems: list[str] = []
    stat = diff_stat(base, head)
    text = diff_text(base, head)

    if stat["added"] > MAX_ADDED_LINES:
        problems.append(f"حجم كبير: {stat['added']} سطر مضاف (حد {MAX_ADDED_LINES}) — قسّم الـ PR.")
    total = stat["added"] + stat["deleted"]
    if total and stat["deleted"] / total > MAX_DELETE_RATIO:
        problems.append(f"نسبة حذف عالية: {stat['deleted']}/{total} — تأكد أن الحذف مقصود.")
    for p in stat["touched"]:
        if p.strip() in PROTECTED_FILES:
            problems.append(f"ملف محمي مُعدّل: {p} — يحتاج مراجعة صريحة.")

    # أسرار في الأسطر المضافة
    current_file, current_line = "", 0
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            current_line = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            for name, rx in PATTERNS:
                m = re.search(rx, line[1:])
                if m and not PLACEHOLDER.match(m.group(0)):
                    problems.append(f"سر مكشوف: {current_file}:{current_line} ({name})")
                    break
            current_line += 1
    return problems


def main() -> int:
    p = argparse.ArgumentParser(prog="pr_check")
    p.add_argument("--base", default="origin/main")
    p.add_argument("--head", default="HEAD")
    args = p.parse_args()

    problems = check(args.base, args.head)
    if not problems:
        print("pr-check: جاهز للدمج — لا مشاكل")
        return 0
    print("pr-check: أوقف وراجع:")
    for x in problems:
        print("  -", x)
    return 1


if __name__ == "__main__":
    sys.exit(main())
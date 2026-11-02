# -*- coding: utf-8 -*-
"""حرس الأسرار — فحص ما سيُرفع إلى Git قبل أن يصل.

الاستخدام:
  python3 scripts/secret_guard.py                  # فحص التغييرات غير المرفوعة
  python3 scripts/secret_guard.py --staged        # فحص المُرحّب (staged) فقط
  python3 scripts/secret_guard.py --scan-history  # فحص آخر 500 كوميت (تاريخي)

القاعدة: أي تطابق يمنع الرفع برمز خروج 1، ويطبع الملف والسطر والنمط.
يُستدعى آليًا من pre-commit hook و GitHub Actions (docs/development-format.md).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# أنماط الأسرار: (اسم، regex) — مقصودة ضيقة لتقليل الإنذارات الكاذبة
PATTERNS = [
    ("Telegram bot token", r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b"),
    ("Supabase secret key", r"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
    ("Supabase publishable", r"\bsb_publishable_[A-Za-z0-9_-]{20,}\b"),
    ("Supabase access token", r"\bsbp_[A-Za-z0-9]{20,}\b"),
    ("OpenRouter/OpenAI key", r"\bsk-or-v1-[A-Za-z0-9]{20,}\b|\bsk-[A-Za-z0-9]{20,}\b"),
    ("AWS access key", r"\bAKIA[A-Z0-9]{16}\b|\bABSK[A-Za-z0-9_-]{20,}\b"),
    ("Bedrock API key", r"\bBedrockAPIKey-[A-Za-z0-9-]{10,}\b"),
    ("Google service key JSON", r"\"type\":\s*\"service_account\""),
    ("GitHub fine-grained PAT", r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ("Generic password assign", r"(?i)(password|passwd|secret|token)\s*[=:]\s*['\"][^'\"\s]{8,}"),
]

# ملفات تُفحص دائمًا بغض النظر عن الامتداد
ALWAYS = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json", "secrets.yaml"}
# مسارات يُتوقع فيها ذكر المفاتيح (توثيق/أمثلة) — تفحص فقط لأنماط القيم الفعلية
EXEMPT = {"docs/connection-guide.md", ".env.example", "docs/development-format.md"}
# قيم مسموحة (متغيرات فارغة أو placeholders)
PLACEHOLDER = re.compile(r"(?i)^(\\*\\*|your[-_]?password\\*\\*|xxx+|\\*\\*\\*|<[^>]*>|\\$\\{?[A-Z_]+\\}?|\\{\\{[^}]*\\}\\}|\\\"\\\")$")


def _git(args: list[str]) -> str:
    return subprocess.run(["git", "-C", str(BASE)] + args, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _check_content(text: str, path: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for name, rx in PATTERNS:
        for m in re.finditer(rx, text):
            val = m.group(0)
            if PLACEHOLDER.match(val):
                continue
            line_no = text[: m.start()].count("\n") + 1
            findings.append((f"{path}:{line_no}", name, val[:12] + "…"))
    return findings


def scan_diff(mode: str) -> list[tuple[str, str, str]]:
    """امسح الأسطر المضافة فقط (الرفع لا يفحص المحذوف)."""
    ref = "HEAD" if mode == "unpushed" else "--cached"
    diff = _git(["diff", "--no-color", "-U0", ref] if mode == "unpushed" else ["diff", "--no-color", "-U0", "--cached"])
    findings: list[tuple[str, str, str]] = []
    current_file = ""
    current_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            current_line = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if current_file in EXEMPT or Path(current_file).name in ALWAYS and content.count("=") == 0:
                pass
            hits = _check_content(content, f"{current_file}:{current_line}")
            findings.extend(hits)
            current_line += 1
    return findings


def scan_history(limit: int = 500) -> list[tuple[str, str, str]]:
    findings = []
    log = _git(["log", f"-{limit}", "--name-only", "--pretty=format:%h"])
    # فحص الملفات الحساسة المسماة في التاريخ فقط (تقرير موجز)
    for line in log.splitlines():
        if line.strip() and not re.match(r"^[0-9a-f]{7,}$", line.strip()):
            if Path(line.strip()).name in ALWAYS and line.strip() not in EXEMPT:
                findings.append((line.strip(), "sensitive-file-in-history", "تحقق يدوي"))
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(prog="secret_guard")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--scan-history", action="store_true")
    args = parser.parse_args()

    if args.scan_history:
        findings = scan_history()
    else:
        findings = scan_diff("staged" if args.staged else "unpushed")

    if not findings:
        print("secret-guard: OK — لا أسرار في التغييرات")
        return 0
    print("secret-guard: ممنوع الرفع — أسرار مكشوفة:")
    for where, name, hint in findings[:30]:
        print(f"  {where} | {name} | {hint}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
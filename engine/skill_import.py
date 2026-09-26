# -*- coding: utf-8 -*-
"""استيراد مهارات خارجية (ECC) إلى الذاكرة الإجرائية — تحت البوابة نفسها، بلا استثناء.

المبدأ: كتالوج خارجي ضخم لا يعني ثقة. كل مهارة مستوردة تدخل كـ CANDIDATE فقط،
وطبقة الخطر لا تنزل أبدًا إلى `low` مهما بدا الوصف بريئًا — لأن النص لم يكتبه المالك.
الترقية تبقى حكرًا على skill_evaluator/skill_admin بالأدلة والتوقيع البشري.

الأوامر:
    python3 engine/skill_import.py scan
    python3 engine/skill_import.py plan   [--filter نص] [--limit N] [--slug a,b]
    python3 engine/skill_import.py import [--filter نص] [--limit N] [--slug a,b]
    python3 engine/skill_import.py status
    python3 engine/skill_import.py drift
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(BASE, "engine") not in sys.path:
    sys.path.insert(0, os.path.join(BASE, "engine"))

from skill_registry import annotate, create_candidate, list_skills, risk_tier  # noqa: E402

SOURCE = "ecc"
DEFAULT_DIR = os.path.join(BASE, "vendor", "ecc", "skills")
MAX_BODY_CHARS = 20000

# التصنيف يعتمد أولًا على **رموز الاسم** (slug) لا على الوصف الحر:
# الوصف نثر تسويقي يوقع في تطابقات كاذبة (مهارة هندسية تُصنَّف «سريرية» لأن وصفها
# ذكر diagnostics)، وتلويث النطاق السريري في وكيل صحي شخصي خطأ لا يُحتمل.
LOCKED_TOKENS = [
    ("clinical", {"clinical", "healthcare", "medical", "patient", "patients", "hipaa", "ehr"}),
    ("security", {
        "security", "secure", "auth", "authn", "authz", "secret", "secrets",
        "credential", "credentials", "vulnerability", "vulnerabilities", "threat",
        "pentest", "exploit", "crypto", "gitleaks", "sast", "owasp", "hardening",
    }),
    ("permissions", {"rbac", "permission", "permissions", "iam", "acl"}),
    ("external_execution", {
        "deploy", "deployment", "deployments", "release", "releases", "publish",
        "publishing", "payment", "payments", "x402", "billing", "checkout", "infra",
        "terraform", "kubernetes", "k8s", "ssh", "shell", "migration", "migrations",
        "production", "rollout", "crosspost", "scraper", "browser", "e2e", "cicd",
    }),
]

REVIEW_TOKENS = [
    ("communications", {
        "writing", "article", "articles", "content", "brand", "marketing", "social",
        "docs", "documentation", "slides", "presentation", "presentations",
        "copywriting", "newsletter", "blog",
    }),
    ("finance", {"pricing", "finance", "financial", "invoice", "billing", "spend", "revenue"}),
    ("staff", {"hiring", "recruiting", "devfleet", "delegation"}),
]

# الوصف يُستشار فقط للطبقات المقفلة، وبعبارات ضيقة لا تحتمل التأويل.
DESC_LOCKED_PATTERNS = [
    ("clinical", r"\b(patient data|patient record|hipaa|clinical trial|medical record|phi)\b"),
    ("security", r"\b(private key|api credential|secret scanning|threat model|vulnerability scan)\b"),
    ("external_execution", r"\b(deploy to production|production deploy|execute shell|run shell commands|process payments)\b"),
]

DEFAULT_DOMAIN = "projects"  # مراجعة بشرية — وهو الافتراضي المقصود

SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private-key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "aws-access-key"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "openai-style-key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", "github-token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{30,}\b", "github-pat"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "slack-token"),
    (r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b", "telegram-bot-token"),
    (r"(?i)\b(api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{24,}", "inline-credential"),
]


# ---------------------------------------------------------------- parsing

def _frontmatter(text):
    """قارئ frontmatter مصغّر — بلا أي اعتمادية جديدة (نفس نهج supabase_client)."""
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in raw.splitlines():
                if not line.strip() or line.startswith("#") or line.startswith(" ") or line.startswith("\t"):
                    continue
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip("\"'")
    return meta, body


def classify(slug, description=""):
    """يعيد (domain, tier). لا يعيد أبدًا طبقة low لمصدر خارجي."""
    tokens = {t for t in re.split(r"[^a-z0-9]+", slug.lower()) if t}
    for domain, keys in LOCKED_TOKENS:
        if tokens & keys:
            return domain, risk_tier(domain)
    desc = description.lower()
    for domain, pattern in DESC_LOCKED_PATTERNS:
        if re.search(pattern, desc):
            return domain, risk_tier(domain)
    for domain, keys in REVIEW_TOKENS:
        if tokens & keys:
            return domain, risk_tier(domain)
    return DEFAULT_DOMAIN, risk_tier(DEFAULT_DOMAIN)


def scan_secrets(text):
    return sorted({label for pat, label in SECRET_PATTERNS if re.search(pat, text)})


def source_dir():
    return os.environ.get("ECC_SKILLS_DIR") or DEFAULT_DIR


def discover(root=None):
    """يمسح مجلد مهارات ECC ويعيد سجلات موحّدة مرتبة."""
    root = root or source_dir()
    out = []
    if not os.path.isdir(root):
        return out
    for slug in sorted(os.listdir(root)):
        path = os.path.join(root, slug, "SKILL.md")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        meta, body = _frontmatter(text)
        name = meta.get("name") or slug
        desc = meta.get("description", "").strip()
        domain, tier = classify(slug, desc)
        out.append({
            "slug": slug,
            "name": name,
            "description": desc,
            "body": body,
            "chars": len(body),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "domain": domain,
            "risk_tier": tier,
            "secrets": scan_secrets(text),
            "path": os.path.relpath(path, BASE).replace("\\", "/"),
        })
    return out


# ---------------------------------------------------------------- registry view

def imported_index():
    """آخر نسخة مستوردة لكل مهارة مصدر: {source_slug: record}."""
    idx = {}
    for rec in list_skills():
        src = rec.get("source") or {}
        if src.get("system") != SOURCE:
            continue
        key = src.get("slug")
        if key and (key not in idx or rec["version"] > idx[key]["version"]):
            idx[key] = rec
    return idx


def decide(item, index, max_chars=MAX_BODY_CHARS):
    """قرار الاستيراد لمهارة واحدة: (action, reason)."""
    if item["secrets"]:
        return "blocked", "أسرار محتملة في النص: " + ", ".join(item["secrets"])
    if not item["description"]:
        return "blocked", "بلا وصف في frontmatter — لا نستورد مهارة مجهولة الغرض"
    if item["chars"] > max_chars:
        return "blocked", f"الجسم {item['chars']} حرفًا > الحد {max_chars} (ميزانية السياق)"
    prev = index.get(item["slug"])
    if prev is None:
        return "new", "جديدة"
    if (prev.get("source") or {}).get("sha256") == item["sha256"]:
        return "unchanged", f"مطابقة للنسخة v{prev['version']} ({prev['status']})"
    return "update", f"تغيّرت عن v{prev['version']} — تُستورد كنسخة جديدة"


def select(items, slugs=None, text_filter=None, limit=None):
    rows = items
    if slugs:
        wanted = {s.strip() for s in slugs if s.strip()}
        rows = [r for r in rows if r["slug"] in wanted]
    if text_filter:
        needle = text_filter.lower()
        rows = [r for r in rows if needle in r["slug"].lower() or needle in r["description"].lower()]
    if limit:
        rows = rows[: int(limit)]
    return rows


# ---------------------------------------------------------------- actions

def plan(root=None, slugs=None, text_filter=None, limit=None):
    items = select(discover(root), slugs, text_filter, limit)
    index = imported_index()
    report = {"new": [], "update": [], "unchanged": [], "blocked": []}
    for item in items:
        action, reason = decide(item, index)
        report[action].append({
            "slug": item["slug"], "domain": item["domain"],
            "risk_tier": item["risk_tier"], "chars": item["chars"], "reason": reason,
        })
    return report


def import_skills(root=None, slugs=None, text_filter=None, limit=None):
    """يستورد المؤهّل فقط كـ CANDIDATE — ولا يفعّل شيئًا."""
    items = select(discover(root), slugs, text_filter, limit)
    index = imported_index()
    created, skipped = [], []
    for item in items:
        action, reason = decide(item, index)
        if action not in {"new", "update"}:
            skipped.append({"slug": item["slug"], "action": action, "reason": reason})
            continue
        rec = create_candidate(
            name=item["name"],
            domain=item["domain"],
            purpose=item["description"],
            procedure=item["body"],
            evidence_ids=[f"{SOURCE.upper()}:{item['slug']}@{item['sha256'][:12]}"],
            confidence=0.5,
        )
        if rec["risk_tier"] == "low":  # حزام أمان: لا يحدث بالتصنيف الحالي، ولو حدث نوقف
            raise AssertionError("imported skill resolved to low tier: " + item["slug"])
        rec = annotate(rec["id"], source={
            "system": SOURCE,
            "slug": item["slug"],
            "sha256": item["sha256"],
            "path": item["path"],
            "license": "MIT (affaan-m/ecc)",
        })
        created.append({"id": rec["id"], "slug": item["slug"], "version": rec["version"],
                        "domain": rec["domain"], "risk_tier": rec["risk_tier"], "action": action})
    return {"created": created, "skipped": skipped}


def status():
    rows = []
    for slug, rec in sorted(imported_index().items()):
        rows.append({"slug": slug, "id": rec["id"], "version": rec["version"],
                     "status": rec["status"], "risk_tier": rec["risk_tier"], "domain": rec["domain"]})
    return rows


def drift(root=None):
    """مهارات مستوردة تغيّر نصها في المصدر — مرشّحة لنسخة جديدة."""
    index = imported_index()
    out = []
    for item in discover(root):
        prev = index.get(item["slug"])
        if prev and (prev.get("source") or {}).get("sha256") != item["sha256"]:
            out.append({"slug": item["slug"], "imported_version": prev["version"],
                        "status": prev["status"]})
    return out


# ---------------------------------------------------------------- cli

def _arg(name, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    slugs = (_arg("--slug") or "").split(",") if _arg("--slug") else None
    text_filter = _arg("--filter")
    limit = _arg("--limit")

    if cmd == "scan":
        items = discover()
        if not items:
            print(f"لا مصدر: {source_dir()} — استنسخ ECC أو عيّن ECC_SKILLS_DIR"); return 1
        for it in select(items, slugs, text_filter, limit):
            flag = "!" if it["secrets"] else " "
            print(f"{flag} {it['slug']:<42} {it['domain']:<20} {it['risk_tier']:<8} {it['chars']:>6}")
        print(f"\nالإجمالي: {len(items)} مهارة في {source_dir()}")
    elif cmd == "plan":
        rep = plan(None, slugs, text_filter, limit)
        for key in ("new", "update", "unchanged", "blocked"):
            print(f"\n== {key} ({len(rep[key])}) ==")
            for r in rep[key][:200]:
                print(f"  {r['slug']:<42} {r['risk_tier']:<8} {r['reason']}")
        print("\nلا شيء كُتب. للتنفيذ: python3 engine/skill_import.py import ...")
    elif cmd == "import":
        res = import_skills(None, slugs, text_filter, limit)
        for r in res["created"]:
            print(f"+ {r['id']} v{r['version']} {r['slug']} → {r['domain']}/{r['risk_tier']} CANDIDATE")
        print(f"\nأُنشئت {len(res['created'])} · تُخطّيت {len(res['skipped'])}")
        print("كلها CANDIDATE — التفعيل يمر بـ skill_evaluator ثم skill_admin approve/activate.")
    elif cmd == "status":
        rows = status()
        for r in rows:
            print(f"{r['id']} v{r['version']:<3} {r['status']:<10} {r['risk_tier']:<8} {r['slug']}")
        print(f"\nمستوردة: {len(rows)}")
    elif cmd == "drift":
        rows = drift()
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

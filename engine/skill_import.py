# -*- coding: utf-8 -*-
"""استيراد مهارات خارجية إلى الذاكرة الإجرائية — تحت البوابة نفسها، بلا استثناء.

المبدأ: كتالوج خارجي ضخم لا يعني ثقة. كل مهارة مستوردة تدخل كـ CANDIDATE فقط،
وطبقة الخطر لا تنزل أبدًا إلى `low` مهما بدا الوصف بريئًا — لأن النص لم يكتبه المالك.
ومن تشحن كودًا تُصعَّد إلى `locked` لأن غرضها تنفيذ لا إرشاد.
الترقية تبقى حكرًا على skill_evaluator/skill_admin بالأدلة والتوقيع البشري.

البنية المتوقعة للمصدر: <الجذر>/<slug>/SKILL.md

الأعلام: --dir الجذر · --source اسم المصدر · --license · --slug a,b · --filter · --limit

الأوامر:
    python3 engine/skill_import.py scan   --dir vendor/ecc/skills --source ecc
    python3 engine/skill_import.py plan   --dir ... --source ... [--filter نص] [--limit N]
    python3 engine/skill_import.py import --dir ... --source ... [--slug a,b]
    python3 engine/skill_import.py status
    python3 engine/skill_import.py drift  --dir ... --source ...
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

# سقف `skill_runtime.context_for` الافتراضي. ما تجاوزه لا يُحمَّل أبدًا بالإعداد الحالي —
# لا نمنعه (قد يرفع المالك السقف) لكن نقوله صراحةً بدل أن يكتشفه بعد الاعتماد.
RUNTIME_CONTEXT_BUDGET = 6000

# ملفات تُنفَّذ. مهارة تشحن كودًا ليست «نصًا إجرائيًا محايدًا»:
# نستورد SKILL.md وحده، فيبقى الكود خارجًا بينما النص يحيل إليه.
EXEC_SUFFIXES = (".py", ".js", ".cjs", ".mjs", ".ts", ".sh", ".bash", ".rb", ".ps1", ".gs")

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


def companions(folder):
    """يعيد (الملفات القابلة للتنفيذ، بقية المرافقات) بجوار SKILL.md."""
    execs, others = [], []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name == "SKILL.md":
                continue
            rel = os.path.relpath(os.path.join(root, name), folder).replace("\\", "/")
            (execs if name.endswith(EXEC_SUFFIXES) else others).append(rel)
    return sorted(execs), sorted(others)


def discover(root=None, system=SOURCE):
    """يمسح مجلد مهارات خارجيًا (<root>/<slug>/SKILL.md) ويعيد سجلات موحّدة مرتبة."""
    root = root or source_dir()
    out = []
    if not os.path.isdir(root):
        return out
    for slug in sorted(os.listdir(root)):
        folder = os.path.join(root, slug)
        path = os.path.join(folder, "SKILL.md")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        meta, body = _frontmatter(text)
        name = meta.get("name") or slug
        desc = meta.get("description", "").strip()
        domain, tier = classify(slug, desc)
        execs, others = companions(folder)

        # تصعيد: مهارة تشحن كودًا تُعامَل كتنفيذ خارجي مهما قال اسمها.
        # نستورد نصها فقط، والنص يحيل إلى سكربتات لا تُنقل — فلا تُفعَّل تلقائيًا أبدًا.
        escalated = bool(execs) and tier != "locked"
        if execs:
            domain, tier = "external_execution", risk_tier("external_execution")

        warnings = []
        if len(body) > RUNTIME_CONTEXT_BUDGET:
            warnings.append(f"يتجاوز سقف التحميل {RUNTIME_CONTEXT_BUDGET} حرفًا — لن يُحمَّل بالإعداد الحالي")
        if execs:
            warnings.append(f"{len(execs)} ملف تنفيذي لا يُستورَد")
        if others:
            warnings.append(f"{len(others)} مرافق (references/data) لا يُستورَد")

        out.append({
            "system": system,
            "slug": slug,
            "registry_slug": f"{system}-{slug}",
            "name": name,
            "description": desc,
            "body": body,
            "chars": len(body),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "domain": domain,
            "risk_tier": tier,
            "escalated": escalated,
            "execs": execs,
            "companions": others,
            "warnings": warnings,
            "secrets": scan_secrets(text),
            "path": os.path.relpath(path, BASE).replace("\\", "/"),
        })
    return out


# ---------------------------------------------------------------- registry view

def imported_index():
    """آخر نسخة مستوردة لكل مهارة: {(system, slug): record}.

    المفتاح مركّب لأن مستودعين مختلفين قد يحملان الاسم نفسه (`design-system`
    موجود في ECC وفي ui-ux-pro-max) — والمفتاح بالـslug وحده كان سيخلط بينهما
    فيظهر المستورد الجديد «نسخة ثانية» من مهارة لا تمت له بصلة.
    """
    idx = {}
    for rec in list_skills():
        src = rec.get("source") or {}
        key = (src.get("system"), src.get("slug"))
        if all(key) and (key not in idx or rec["version"] > idx[key]["version"]):
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
    prev = index.get((item["system"], item["slug"]))
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

def plan(root=None, slugs=None, text_filter=None, limit=None, system=SOURCE):
    items = select(discover(root, system), slugs, text_filter, limit)
    index = imported_index()
    report = {"new": [], "update": [], "unchanged": [], "blocked": []}
    for item in items:
        action, reason = decide(item, index)
        report[action].append({
            "slug": item["slug"], "domain": item["domain"], "risk_tier": item["risk_tier"],
            "chars": item["chars"], "reason": reason, "escalated": item["escalated"],
            "warnings": item["warnings"],
        })
    return report


def import_skills(root=None, slugs=None, text_filter=None, limit=None, system=SOURCE, license_note=""):
    """يستورد المؤهّل فقط كـ CANDIDATE — ولا يفعّل شيئًا."""
    items = select(discover(root, system), slugs, text_filter, limit)
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
            evidence_ids=[f"{system.upper()}:{item['slug']}@{item['sha256'][:12]}"],
            confidence=0.5,
            slug=item["registry_slug"],
        )
        if rec["risk_tier"] == "low":  # حزام أمان: لا يحدث بالتصنيف الحالي، ولو حدث نوقف
            raise AssertionError("imported skill resolved to low tier: " + item["slug"])
        rec = annotate(rec["id"], source={
            "system": system,
            "slug": item["slug"],
            "sha256": item["sha256"],
            "path": item["path"],
            "license": license_note or "انظر مستودع المصدر",
            "escalated_for_executables": item["escalated"],
            "not_imported": {"executables": len(item["execs"]), "companions": len(item["companions"])},
            "warnings": item["warnings"],
        })
        created.append({"id": rec["id"], "slug": item["slug"], "version": rec["version"],
                        "domain": rec["domain"], "risk_tier": rec["risk_tier"], "action": action,
                        "escalated": item["escalated"], "warnings": item["warnings"]})
    return {"created": created, "skipped": skipped}


def status():
    rows = []
    for (system, slug), rec in sorted(imported_index().items()):
        rows.append({"system": system, "slug": slug, "id": rec["id"], "version": rec["version"],
                     "status": rec["status"], "risk_tier": rec["risk_tier"], "domain": rec["domain"]})
    return rows


def drift(root=None, system=SOURCE):
    """مهارات مستوردة تغيّر نصها في المصدر — مرشّحة لنسخة جديدة."""
    index = imported_index()
    out = []
    for item in discover(root, system):
        prev = index.get((item["system"], item["slug"]))
        if prev and (prev.get("source") or {}).get("sha256") != item["sha256"]:
            out.append({"system": system, "slug": item["slug"],
                        "imported_version": prev["version"], "status": prev["status"]})
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
    system = _arg("--source", SOURCE)
    root = _arg("--dir")
    license_note = _arg("--license", "")

    if cmd == "scan":
        items = discover(root, system)
        if not items:
            print(f"لا مصدر: {root or source_dir()} — استنسخ المستودع أو عيّن --dir / ECC_SKILLS_DIR")
            return 1
        for it in select(items, slugs, text_filter, limit):
            flag = "!" if it["secrets"] else ("^" if it["escalated"] else " ")
            print(f"{flag} {it['slug']:<42} {it['domain']:<20} {it['risk_tier']:<8} {it['chars']:>6}"
                  + ("  ⚠ " + " · ".join(it["warnings"]) if it["warnings"] else ""))
        print(f"\nالإجمالي: {len(items)} مهارة في {root or source_dir()}  (^ = صُعّدت لشحنها كودًا)")
    elif cmd == "plan":
        rep = plan(root, slugs, text_filter, limit, system)
        for key in ("new", "update", "unchanged", "blocked"):
            print(f"\n== {key} ({len(rep[key])}) ==")
            for r in rep[key][:200]:
                mark = "^" if r.get("escalated") else " "
                print(f" {mark}{r['slug']:<42} {r['risk_tier']:<8} {r['reason']}")
                for w in r.get("warnings", []):
                    print(f"    ⚠ {w}")
        print("\nلا شيء كُتب. للتنفيذ: python3 engine/skill_import.py import ...")
    elif cmd == "import":
        res = import_skills(root, slugs, text_filter, limit, system, license_note)
        for r in res["created"]:
            mark = " ^صُعّدت" if r["escalated"] else ""
            print(f"+ {r['id']} v{r['version']} {r['slug']} → {r['domain']}/{r['risk_tier']} CANDIDATE{mark}")
            for w in r["warnings"]:
                print(f"    ⚠ {w}")
        print(f"\nأُنشئت {len(res['created'])} · تُخطّيت {len(res['skipped'])}")
        print("كلها CANDIDATE — التفعيل يمر بـ skill_evaluator ثم skill_admin approve/activate.")
    elif cmd == "status":
        rows = status()
        for r in rows:
            print(f"{r['id']} v{r['version']:<3} {r['status']:<10} {r['risk_tier']:<8} {r['system']}/{r['slug']}")
        print(f"\nمستوردة: {len(rows)}")
    elif cmd == "drift":
        print(json.dumps(drift(root, system), ensure_ascii=False, indent=2))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

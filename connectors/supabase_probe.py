# -*- coding: utf-8 -*-
"""فحص مشروع Supabase عن بُعد — **بالمفتاح العام فقط، ولا يحتاج المفتاح السري**.

لماذا هذه الوحدة
---------------
سؤال متكرر: «هل نُفِّذت ملفات SQL على هذا المشروع أم لا؟» والجواب لا يحتاج أي
صلاحية كتابة ولا قراءة بيانات سرية: يكفي أن نسأل PostgREST عن كل جدول ودالة.
المفتاح العام (`sb_publishable_…` / `anon`) **مخصَّص للنشر العام** — وضعه في رابط
أو في أداة فحص لا يكشف شيئًا، لأن RLS يحجب كل صف عنه أصلًا.

التمييز الذي تعتمد عليه الأداة (مُجرَّب فعليًا):

| الرد | المعنى |
|---|---|
| `404` + `PGRST205` (جدول) | **غير موجود** — الملف لم يُنفَّذ |
| `404` + `PGRST202` (دالة) | **غير موجودة** — الملف لم يُنفَّذ |
| `401`/`403` «permission denied» | **موجود** — وهو الأفضل أمنيًا: موجود ومحجوب |
| `200` + قائمة | موجود… لكن صلاحية ممنوحة للعام (تحقّق من REVOKE) |
| «no API key» | المفتاح العام مفقود أو خطأ |

رفض المفتاح السري (قاعدة أمنية مُنفَّذة في الكود)
-----------------------------------------------
`--key` يرفض أي مفتاح سري: `sb_secret_…` أو JWT يحمل `role: service_role`. السبب
ليس شكليًا: هذا الفحص لا يحتاج المفتاح السري، وأي مسار يجعل المفتاح السري يمر في
سطر أوامر أو في سجل هو مسار يمكن أن يُسجَّل ويُنسخ — والمفتاح السري يقرأ ويكتب كل
صف ويتجاوز RLS. الفحص بالعام يعطي الجواب نفسه.

الاستخدام:
    export SUPABASE_URL="https://<ref>.supabase.co"
    export SUPABASE_ANON_KEY="sb_publishable_…"
    python3 -m connectors.supabase_probe
    python3 -m connectors.supabase_probe --json
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# كل ما تنشئه ملفات supabase/*.sql — الجرد نفسه الذي تَعِد به صفحة الإعداد.
TABLES = ("state_snapshots", "tasks_mirror", "brain_episodes",
          "brain_facts", "brain_working")
FUNCTIONS = ("brain_norm", "brain_fold", "brain_recall", "brain_stats", "brain_prune")

SECRET_PREFIXES = ("sb_secret_",)


def reject_secret_key(key: str) -> str:
    """يعيد سبب الرفض إن كان المفتاح سريًا، وإلا نصًّا فارغًا."""
    text = (key or "").strip()
    if not text:
        return ""
    for prefix in SECRET_PREFIXES:
        if text.startswith(prefix):
            return "المفتاح سري (sb_secret_…) — الفحص لا يحتاجه ولا يقبله"
    if text.count(".") == 2 and text.startswith("eyJ"):
        payload = text.split(".")[1]
        try:
            padded = payload + "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
        except Exception:  # noqa: BLE001 - JWT غير مقروء لا يعني سرًّا
            return ""
        if str(claims.get("role") or "") == "service_role":
            return "المفتاح JWT يحمل role=service_role — الفحص لا يحتاجه ولا يقبله"
    return ""


def normalize_url(url: str) -> str:
    """يقبل `https://<ref>.supabase.co` فقط — لا روابط لوحة التحكم."""
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    if "supabase.com/dashboard" in text:
        return ""
    if not re.match(r"^https://[a-z0-9-]+\.supabase\.(co|in)$", text):
        return ""
    return text


def _default_open(url: str, timeout: int = 15):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)


def _classify(status: int, body: str, kind: str) -> tuple:
    """يعيد (الحالة, الشرح). الحالة: exists · missing · open · unknown."""
    text = (body or "").strip()
    code = ""
    match = re.search(r'"code"\s*:\s*"([^"]+)"', text)
    if match:
        code = match.group(1)
    lowered = text.lower()

    # الترتيب مقصود، وله أثر حقيقي: فحص المفتاح **قبل** فحص الحجب. لو كان
    # العكس، لصار مفتاح خاطئ (401) يُقرأ كـ«موجود ومحجوب» — أي تقرير كاذب بأن
    # الإعداد تمّ. رصده اختبار، لا مراجعة بشرية.
    if ("no api key" in lowered or "invalid api key" in lowered
            or code in ("PGRST301", "PGRST302")):
        return "unknown", "المفتاح العام غير مقبول — تحقق من SUPABASE_ANON_KEY"
    if status == 404 and code in ("PGRST205", "PGRST202"):
        return "missing", ("غير موجود — الملف لم يُنفَّذ" if kind == "table"
                           else "غير موجودة — الملف لم يُنفَّذ")
    if status in (401, 403) or "permission denied" in lowered:
        return "exists", "موجود ومحجوب عن العام (وهذا هو الوضع الصحيح)"
    if status == 200:
        if text in ("[]", "") or text.startswith("["):
            return "open", "موجود وله صلاحية قراءة للعام — راجع REVOKE في ملف SQL"
        return "exists", "موجود ويستجيب"
    return "unknown", f"رد غير متوقع (HTTP {status})"


def probe(base_url: str, key: str, *, opener=None, timeout: int = 15) -> dict:
    """يفحص الجداول والدوال. لا يكتب شيئًا ولا يقرأ أي صف."""
    opener = opener or (lambda url, timeout=timeout: _default_open(url, timeout))
    report = {"base_url": base_url, "tables": {}, "functions": {},
              "present": 0, "missing": [], "unknown": [], "verdict": ""}

    for name in TABLES:
        url = f"{base_url}/rest/v1/{name}?select=id&limit=1&apikey={urllib.parse.quote(key)}"
        report["tables"][name] = _fetch(url, opener, "table")
    for name in FUNCTIONS:
        url = f"{base_url}/rest/v1/rpc/{name}?apikey={urllib.parse.quote(key)}"
        report["functions"][name] = _fetch(url, opener, "function")

    everything = {**report["tables"], **report["functions"]}
    for name, info in everything.items():
        if info["state"] in ("exists", "open"):
            report["present"] += 1
        elif info["state"] == "missing":
            report["missing"].append(name)
        else:
            report["unknown"].append(name)

    total = len(everything)
    if report["missing"] and report["present"] == 0:
        report["verdict"] = "لم يبدأ الإعداد: لا جدول ولا دالة موجودة على هذا المشروع"
    elif report["missing"]:
        report["verdict"] = f"إعداد ناقص: {total - len(report['missing'])} من {total} موجود"
    elif report["unknown"]:
        report["verdict"] = "تعذّر الفحص — تحقق من الرابط والمفتاح والشبكة"
    else:
        report["verdict"] = f"الإعداد مكتمل: {total} من {total} موجود"
    return report


def _fetch(url: str, opener, kind: str) -> dict:
    try:
        response = opener(url)
        status = getattr(response, "status", 200)
        body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
    except Exception as exc:  # noqa: BLE001 - الشبكة لا تُسقط الأداة
        return {"state": "unknown", "detail": f"تعذّر الاتصال: {type(exc).__name__}"}
    state, detail = _classify(status, body, kind)
    return {"state": state, "detail": detail, "http": status}


def load_settings(env=None) -> tuple:
    """يعيد (base_url, key, مشكلة). يقبل خرائط البيئة كما في بقية الموصلات."""
    env = os.environ if env is None else env
    url = normalize_url(env.get("SUPABASE_URL", ""))
    key = (env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not url:
        return "", "", ("SUPABASE_URL غير مضبوط أو ليس https://<ref>.supabase.co"
                        " (روابط لوحة التحكم مرفوضة)")
    if not key:
        return "", "", "SUPABASE_ANON_KEY غير مضبوط (المفتاح العام — لا السري)"
    reason = reject_secret_key(key)
    if reason:
        return "", "", f"{reason} — استخدم SUPABASE_ANON_KEY"
    return url, key, ""


ICON = {"exists": "✅", "open": "⚠️", "missing": "❌", "unknown": "❓"}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    url, key, problem = load_settings()
    if problem:
        print(f"❌ {problem}", file=sys.stderr)
        return 2

    report = probe(url, key)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["missing"] else 1

    print(f"فحص المشروع: {url}")
    print(f"  (بالمفتاح العام — لا كتابة ولا قراءة صفوف)\n")
    print("  الجداول:")
    for name, info in report["tables"].items():
        print(f"    {ICON[info['state']]} {name:18s} {info['detail']}")
    print("  الدوال (RPC):")
    for name, info in report["functions"].items():
        print(f"    {ICON[info['state']]} {name:18s} {info['detail']}")
    print(f"\n  الخلاصة: {report['verdict']}")
    if report["missing"]:
        print("  الناقص: " + "، ".join(report["missing"]))
        print("  للتنفيذ: افتح صفحة الإعداد docs/sql-setup-page.html")
    return 0 if not report["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

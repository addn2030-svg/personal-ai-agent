# -*- coding: utf-8 -*-
"""
سجل الأصول المعرفية — التتبع الخلفي الموحد لكل شيء:
  الكتب (من شيت المصادر) · مستندات وتبويبات Google Drive · الملفات المحلية
  (مواد تدريبية، أدلة، حزم أوامر، مرفوعات، عقود) — يتزامن تلقائيًا مع كل دورة كاملة.

التشغيل:  python3 engine/asset_registry.py
الواجهة:  reports/registry-latest.html  (تصفية وبحث، تعمل دون اتصال)
"""
import datetime as dt
import glob
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TODAY = dt.date.today()
SHEET_URL = "https://docs.google.com/spreadsheets/d/1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc/edit"
DOC_URL = "https://docs.google.com/document/d/1xhcUfNXZRK5hoOsKdGHh6HSdiN6-kyMkS1RRtoLl-kw/edit"
SHEET_TABS = ["خطة الإنجاز والمهام", "لوحة التحكم الأسبوعية", "تسلسل الأبواب والأهداف",
              "المال E-S-B-I", "المالية يوليو 2026", "تعليمات تجاوز نقاط الضعف",
              "المصادر والتعلم العلمي", "مكتبة العبارات الجاهزة", "سجل الطاقة والتعافي",
              "سجل القرارات الموثقة", "شجرة الأبواب والمؤشرات"]


def collect(S):
    assets = []

    # 1) الكتب والمصادر العلمية (من knowledge_sources)
    for k in S.get("knowledge_sources", []):
        assets.append({"title": k["source"], "type": "كتاب/مصدر", "status": k.get("status", "لم يبدأ"),
                       "location": k.get("youtube") or "شيت المصادر — تبويب Google",
                       "door": "التعلم والقراءة", "detail": k.get("key_idea", ""),
                       "link": k.get("youtube") or SHEET_URL, "sensitive": False})

    # 2) تبويبات الشيت + مستند Drive
    for t in SHEET_TABS:
        assets.append({"title": f"شيت: {t}", "type": "تبويب شيت", "status": "مرجع حي",
                       "location": "Google Sheets", "door": "—", "detail": "", "link": SHEET_URL, "sensitive": False})
    assets.append({"title": "خطة أسبوع سرعة الحسم V2 (20–26 أغسطس)", "type": "مستند Drive",
                   "status": "نشطة", "location": "Google Docs", "door": "التطوير الشخصي",
                   "detail": "بروتوكول بطء الحسم — 7 أيام", "link": DOC_URL, "sensitive": False})

    # 3) المواد التدريبية والأدلة وحزم الأوامر (محلي)
    local_defs = [
        ("materials/*.md", "مادة تدريبية", "التعلم والقراءة"),
        ("docs/*.md", "دليل", "—"),
        ("prompts/*.md", "حزمة أوامر وكيل", "الذكاء الاصطناعي"),
        ("tools/*.html", "أداة", "الذكاء الاصطناعي"),
        ("evaluation/*.md", "مراجعة معمارية", "—"),
    ]
    for pat, typ, door in local_defs:
        for f in glob.glob(os.path.join(BASE, pat)):
            name = os.path.basename(f)
            assets.append({"title": name.replace("-", " ").rsplit(".", 1)[0], "type": typ,
                           "status": "مرجع", "location": f"محلي: {pat.split('/')[0]}/{name}",
                           "door": door, "detail": "", "link": "", "sensitive": False})

    # 4) المرفوعات (عقود ولقطات — خاصة)
    for f in glob.glob(os.path.join(BASE, "..", "uploads", "*")):
        name = os.path.basename(f)
        if not name:
            continue
        is_contract = "عقد" in name or "pdf" in name.lower()
        assets.append({"title": name, "type": "مستند قانوني 📜" if is_contract else "مرفق",
                       "status": "خاص — محلل" if is_contract else "مرفق",
                       "location": "uploads/", "door": "الأعمال والمشاريع" if is_contract else "—",
                       "detail": "التحليل: reports/contract-alzaman-analysis.md" if is_contract else "",
                       "link": "", "sensitive": is_contract})

    # 5) خطط التعلّم
    for p in S.get("learning_plans", []):
        assets.append({"title": f"خطة تعلم: {p['title']}", "type": "خطة تعلم",
                       "status": p["status"], "location": p.get("material_file") or "learning_engine",
                       "door": "التعلم والقراءة", "detail": f"{p['plan_id']} — منهجية ILPC",
                       "link": "", "sensitive": False})
    return assets


def sync():
    store = Store()
    S = store.rows_all()
    fresh = collect(S)
    key = lambda a: (a["title"], a["location"])
    old = {key(a): a for a in S.get("asset_registry", [])}
    merged, added = [], 0
    for a in fresh:
        if key(a) not in old:
            a["asset_id"] = f"AS-{len(old) + len(merged) + added + 1:03d}"
            a["added_at"] = TODAY.isoformat()
            a["last_touched"] = TODAY.isoformat()
            added += 1
        else:
            prev = old[key(a)]
            a["asset_id"] = prev.get("asset_id", f"AS-{len(merged)+1:03d}")
            a["added_at"] = prev.get("added_at")
            a["last_touched"] = prev.get("last_touched", TODAY.isoformat())
        merged.append(a)
    S["asset_registry"] = merged
    if added:
        store.commit(S, "asset_registry_sync", added=added, total=len(merged))
        log_event("ASSET_REGISTRY_SYNC", added=added, total=len(merged))
    print(f"🗂️ سجل الأصول: {len(merged)} أصلًا ({added} جديدًا هذا المزامنة)")
    return merged


def render(assets):
    from render_html import esc, CSS
    counts = {}
    for a in assets:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    chips = "".join(f'<button class="chip" onclick="filter(\'\')" data-t="">{esc(t)} ({counts[t]})</button>'
                    for t in sorted(counts, key=counts.get, reverse=True))
    rows = "".join(
        f'<div class="item" data-t="{esc(a["type"])}" data-s="{esc(a["status"])}">'
        f'<span class="tag">{esc(a["type"])}</span> <b>{esc(a["title"])}</b> '
        f'<span class="pill">{esc(a["status"])}</span>'
        + (f' <span class="pill warn">{esc(a["door"])}</span>' if a["door"] not in ("", "—") else "")
        + (f'<br><span class="loc">{esc(a["detail"] or a["location"])}</span>' if (a["detail"] or a["location"]) else "")
        + (f' <a href="{esc(a["link"])}" target="_blank">↗</a>' if a["link"] else "")
        + "</div>"
        for a in assets)
    html = f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🗂️ سجل الأصول — ملفاتك وكتبك ومستنداتك</title>
<style>{CSS}
.chip{{border:1px solid #cfd9e2;background:#fff;border-radius:18px;padding:6px 12px;font-size:12.5px;cursor:pointer;font-family:inherit;margin:0 4px 6px 0}}
.chip.on{{background:#0e4a50;color:#fff;border-color:#0e4a50}}
.item{{background:#fff;border:1px solid #e3e9f0;border-radius:12px;padding:10px 14px;margin:8px 0;font-size:13.5px}}
.tag{{background:#e0f2f1;color:#0e4a50;border-radius:14px;padding:1px 10px;font-size:11.5px;font-weight:700}}
.pill{{background:#eef2f6;border-radius:14px;padding:1px 9px;font-size:11px}}
.loc{{color:#6b7c8a;font-size:12px}}
input{{width:100%;padding:10px 14px;border:1.5px solid #cdd9e2;border-radius:10px;font-family:inherit;font-size:14px;margin:10px 0}}
a{{color:#137a74}}
</style></head><body>
<div class="topbar"><div class="logo">🗂️</div>
<div class="brand"><b>سجل الأصول المعرفية</b><span>كل الملفات والكتب والمستندات في مكان واحد — مزامنة تلقائية مع كل دورة</span></div>
<div class="spacer"></div><span class="badge live">{len(assets)} أصلًا</span></div>
<div class="wrap">
<input placeholder="🔍 ابحث بالاسم..." onkeyup="q=this.value;apply()">
<div>{chips}</div>
{rows}
</div>
<script>
function filter(t){{document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c.dataset.t===t));window.t=t;apply()}}
function apply(){{document.querySelectorAll('.item').forEach(i=>{{
 var okT=!window.t||i.dataset.t===window.t;
 var okQ=!window.q||i.innerText.includes(window.q);
 i.style.display=(okT&&okQ)?'':'none'}})}}
</script></body></html>"""
    out = os.path.join(BASE, "reports", "registry-latest.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"✅ الواجهة: reports/registry-latest.html")


if __name__ == "__main__":
    render(sync())

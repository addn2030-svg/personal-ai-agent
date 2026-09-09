# -*- coding: utf-8 -*-
"""
مولّد الخرائط الذهنية الهيكلية (Mermaid Mind Maps) — v0.9.

النمط المعتمد: عند تلخيص أي كتاب/محاضرة/فيديو ينتج الوكيل خريطة ذهنية بهذا
النسق:

    mindmap
      root((العنوان))
        فرع
          ورقة
          ورقة

كل خريطة تُحفظ في:
  • reports/mindmaps/mm-XXX.mmd        ← صيغة Mermaid نصية (تُلصق في mermaid.live /
                                          Obsidian / GitHub Markdown)
  • reports/mindmaps/mm-XXX.md         ← تقرير عربي RTL يتضمن كود Mermaid + الشجرة
                                          النصية الاحتياطية (تعمل دون إنترنت)
  • reports/mindmaps/mm-XXX.html       ← صفحة HTML بسيطة تعرض الشجرة النصية
• وتُسجَّل في قسم mind_maps بمخزن الحالة (مع branch_model للاستخدام اللاحق).

التشغيل:
  python3 engine/mindmap.py demo                       ← نموذجان: الخريطة الأم + مادة حقيقية
  python3 engine/mindmap.py build --title "..." --file notes.md
  python3 engine/mindmap.py weekly --date 2026-09-18   ← خريطة الجمعة الأسبوعية

المصدر المرجعي للخريطة الأم: engine/master_os.py (MASTER_MIND_MAP_BRANCHES).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from master_os import MASTER_MIND_MAP_TITLE, MASTER_MIND_MAP_BRANCHES
from store import Store, log_event

REPORTS = os.path.join(BASE, "reports")
MAP_DIR = os.path.join(REPORTS, "mindmaps")
os.makedirs(MAP_DIR, exist_ok=True)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
CHECK_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$")


def sun_of(d: dt.date) -> dt.date:
    """أحد الأسبوع (بداية أسبوع العمل السعودي = الأحد)."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def slugify(text: str) -> str:
    out = re.sub(r"[^\w\u0600-\u06FF]+", "-", text).strip("-").lower()
    return out[:40] or "map"


def parse_markdown(md_text: str, fallback_title: str):
    """يفحص Markdown عادي إلى شجرة ذهنية.

    - #  → جذر (العنوان)
    - ## → فرع، ### → فرع فرعي، وهكذا
    - "- نقطة" → ورقة تحت أقرب فرع

    يعيد: (title, sections) حيث sections = [{"branch":..,"sub_branches":[{"name":..,
    "leaves":[]}],"leaves":[]}]
    """
    root_title = fallback_title
    branches = []          # [{branch, sub_branches:[{name, leaves}], leaves}]
    current = None         # dict فرع
    current_sub = None     # dict فرع فرعي

    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                root_title = title
            elif level == 2:
                current = {"branch": title, "sub_branches": [], "leaves": []}
                branches.append(current)
                current_sub = None
            elif level >= 3:
                if current is None:
                    current = {"branch": title, "sub_branches": [], "leaves": []}
                    branches.append(current)
                sub = {"name": title, "leaves": []}
                current["sub_branches"].append(sub)
                current_sub = sub
            continue
        m = CHECK_RE.match(line) or BULLET_RE.match(line)
        if m:
            leaf = m.group(1).strip()
            if current is None:
                current = {"branch": "نقاط رئيسية", "sub_branches": [], "leaves": []}
                branches.append(current)
            if current_sub is not None:
                current_sub["leaves"].append(leaf)
            else:
                current["leaves"].append(leaf)
    return root_title, branches


def mermaid_of(title: str, sections) -> str:
    """يولّد نص Mermaid mindmap من بنية الفروع."""
    lines = ["mindmap", f"  root(({title}))"]
    for b in sections:
        lines.append(f"    {b['branch']}")
        for leaf in b.get("leaves", []):
            lines.append(f"      {leaf}")
        for sub in b.get("sub_branches", []):
            lines.append(f"      {sub['name']}")
            for leaf in sub.get("leaves", []):
                lines.append(f"        {leaf}")
    return "\n".join(lines)


def tree_of(title: str, sections) -> str:
    """شجرة نصية احتياطية (تُعرض دون إنترنت وفي الطباعة/PDF)."""
    out = [f"{title}", "=" * len(title)]
    for i, b in enumerate(sections):
        last_b = i == len(sections) - 1
        out.append(("└── " if last_b else "├── ") + b["branch"])
        kids = list(b.get("leaves", [])) + [
            f"◈ {s['name']}" + (f" — {'، '.join(s['leaves'])}" if s.get("leaves") else "")
            for s in b.get("sub_branches", [])]
        for j, leaf in enumerate(kids):
            last_k = j == len(kids) - 1
            prefix = "    " if last_b else "│   "
            out.append(prefix + ("└── " if last_k else "├── ") + leaf)
    return "\n".join(out)


def _content_hash(title, sections):
    raw = title + "|" + "|".join(
        b["branch"] + ">".join(b.get("leaves", [])) + ">".join(
            s["name"] + "/" + ".".join(s.get("leaves", [])) for s in b.get("sub_branches", []))
        for b in sections)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _save_report(row, mermaid_txt, tree_txt):
    mmd = os.path.join(MAP_DIR, row["file_mmd"])
    md = os.path.join(MAP_DIR, row["file_md"])
    with open(mmd, "w", encoding="utf-8") as fh:
        fh.write(mermaid_txt + "\n")
    md_body = f"""# 🗺️ {row['title']}

> خريطة ذهنية {row['topic']} — المصدر: {row['source_ref']} ({row['created_at']})
> التوليد: engine/mindmap.py — للعرض المرئي الصق كود Mermaid في
> mermaid.live أو Obsidian أو أي محرر Mermaid (لا حاجة لإنترنت في الشجرة النصية).

## كود Mermaid (mindmap)

```mermaid
{mermaid_txt}
```

## الشجرة النصية

```text
{tree_txt}
```
"""
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(md_body)
    return md


def register(title, sections, topic, source_kind, source_ref, store=None,
             weekly=False, week_key=None, digest_id=None, force=False):
    """بناء ملفات الخريطة + تسجيلها في قسم mind_maps (idempotent بالمحتوى)."""
    store = store or Store()
    chash = _content_hash(title, sections)
    S = store.rows_all()
    existing = S.get("mind_maps", [])
    dupe = None
    if weekly and week_key:
        # أسبوعية: تكرار لنفس الأسبوع لا يُنشئ خريطة جديدة مهما تغيّر المحتوى
        dupe = next((m for m in existing if m.get("weekly")
                     and m.get("week_key") == week_key), None)
    if dupe is None:
        # تطابق بالمحتوى (hash) أو بنيويًا لصفوف المرجع المسجلة (بدون hash)
        dupe = next((m for m in existing if not m.get("weekly")
                     and m.get("topic") == topic and (
                         m.get("content_hash") == chash
                         or (not m.get("content_hash")
                             and m.get("title") == title
                             and m.get("branch_model") == sections))),
                    None)
    if dupe and not force:
        if dupe.get("file_md"):
            return dupe, False
        # صف مرجعي مسجّل بلا ملفات (مثل MM-000 من البذرة): نولّد ملفاته ونرقّيه
        mermaid_txt = mermaid_of(title, sections)
        tree_txt = tree_of(title, sections)
        dupe.update({
            "content_hash": chash,
            "file_mmd": f"{dupe['map_id'].lower()}.mmd",
            "file_md": f"{dupe['map_id'].lower()}.md",
            "created_at": dt.date.today().isoformat(),
            "status": "READY",
        })
        _save_report(dupe, mermaid_txt, tree_txt)
        html = _offline_html(title, tree_txt, mermaid_txt, dupe["map_id"])
        with open(os.path.join(MAP_DIR, f"{dupe['map_id'].lower()}.html"),
                  "w", encoding="utf-8") as fh:
            fh.write(html)
        S["mind_maps"] = existing
        store.commit(S, "mindmap_filled_reference", map_id=dupe["map_id"])
        log_event("mindmap_filled_reference", map_id=dupe["map_id"])
        return dupe, True

    used = {int(m["map_id"].split("-")[1]) for m in existing
            if m.get("map_id", "").startswith("MM-")}
    n = 1
    while n in used:
        n += 1
    map_id = f"MM-{n:03d}"
    row = {
        "map_id": map_id,
        "title": title,
        "topic": topic,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "created_at": dt.date.today().isoformat(),
        "content_hash": chash,
        "file_mmd": f"{map_id.lower()}.mmd",
        "file_md": f"{map_id.lower()}.md",
        "branch_model": sections,
        "weekly": weekly,
        "week_key": week_key,
        "digest_id": digest_id,
        "status": "READY",
    }
    mermaid_txt = mermaid_of(title, sections)
    tree_txt = tree_of(title, sections)
    _save_report(row, mermaid_txt, tree_txt)
    # HTML سطر بسيط للعرض السريع
    html = _offline_html(title, tree_txt, mermaid_txt, map_id)
    with open(os.path.join(MAP_DIR, f"{map_id.lower()}.html"), "w",
              encoding="utf-8") as fh:
        fh.write(html)

    if force and dupe:
        existing = [m for m in existing if m.get("map_id") != dupe.get("map_id")]
    existing.append(row)
    S["mind_maps"] = existing
    store.commit(S, "mindmap_register", map_id=map_id, topic=topic)
    log_event("mindmap_built", map_id=map_id, title=title, hash=chash)
    return row, True


def _offline_html(title, tree_txt, mermaid_txt, map_id):
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🗺️ {esc(title)} — خريطة ذهنية {esc(map_id)}</title>
<style>
body{{font-family:'Segoe UI',Tahoma,sans-serif;direction:rtl;margin:0;background:#f4f6f8;color:#1c2b36}}
.top{{background:linear-gradient(120deg,#3d1e6e,#6a3fc0);color:#fff;padding:16px 22px}}
pre{{background:#fff;border:1px solid #ddd;border-radius:12px;padding:14px 18px;overflow:auto;line-height:1.6;font-size:13.5px;direction:ltr;text-align:left}}
.wrap{{max-width:860px;margin:0 auto;padding:18px}}
h2{{color:#3d1e6e;border-right:4px solid #6a3fc0;padding-right:10px}}
.btn{{display:inline-block;border:none;background:#6a3fc0;color:#fff;border-radius:10px;padding:8px 16px;font-family:inherit;cursor:pointer}}
</style></head><body>
<div class="top"><b>🗺️ {esc(title)}</b> &nbsp;·&nbsp; {esc(map_id)} · <small>خريطة ذهنية Mermaid — تعمل دون إنترنت</small></div>
<div class="wrap">
<h2>🌳 الشجرة النصية (احتياطية — للطباعة/PDF)</h2>
<pre style="direction:rtl;text-align:right">{esc(tree_txt)}</pre>
<h2>🧩 كود Mermaid — للعرض المرئي في mermaid.live / Obsidian</h2>
<button class="btn" onclick="var t=document.getElementById('mm');navigator.clipboard.writeText(t.innerText);this.textContent='✅ نُسخ'">📋 نسخ الكود</button>
<pre id="mm">{esc(mermaid_txt)}</pre>
</div></body></html>"""


def build_from_markdown(title, md_text, topic="generic", source_kind="notes",
                        source_ref="ملف نصي", store=None):
    parsed_title, sections = parse_markdown(md_text, title or "خريطة ذهنية")
    row, created = register(parsed_title or title, sections, topic, source_kind,
                            source_ref, store=store)
    verb = "أُنشئت" if created else "موجودة أصلًا (idempotent)"
    print(f"{'✅' if created else '🔁'} الخريطة {row['map_id']} — {verb}")
    print(f"   العنوان: {row['title']}")
    print(f"   Mermaid: reports/mindmaps/{row['file_mmd']}")
    print(f"   تقرير:   reports/mindmaps/{row['file_md']}")
    return row, created


def build_demo(store=None):
    """نموذجان: الخريطة الأم للنظام + خريطة من مادة حقيقية في المستودع."""
    created = []
    # 1) الخريطة الأم المعتمدة (نموذج النسق)
    sections = [{"branch": b, "sub_branches": [], "leaves": leaves}
                for (b, leaves) in MASTER_MIND_MAP_BRANCHES]
    row, is_new = register(MASTER_MIND_MAP_TITLE, sections, topic="master-os",
                           source_kind="system-reference",
                           source_ref="معمارية v0.9 — الخريطة الأم المعتمدة",
                           store=store)
    print(f"{'✅' if is_new else '🔁'} الخريطة الأم {row['map_id']} — {row['title']}")
    print(f"   Mermaid: reports/mindmaps/{row['file_mmd']}")
    created.append((row["map_id"], is_new))
    # 2) مادة تدريبية حقيقية من المستودع (مثال قابل للتكرار)
    material = os.path.join(BASE, "materials", "lp-001-lean-six-sigma-ilpc.md")
    if os.path.exists(material):
        txt = open(material, encoding="utf-8").read()
        row2, is_new2 = build_from_markdown(
            "Lean Six Sigma في قسم التأهيل — ILPC", txt, topic="learning",
            source_kind="training-material",
            source_ref="materials/lp-001-lean-six-sigma-ilpc.md", store=store)
        created.append((row2["map_id"], is_new2))
    return created


def build_weekly(ref_date=None, store=None):
    """خريطة الجمعة الأسبوعية: من ملخص الأسبوع الأبرز (كتاب/محاضرة/مادة)."""
    store = store or Store()
    S = store.rows_all()
    if ref_date is None:
        ref_date = dt.date.today()
    elif isinstance(ref_date, str):
        ref_date = dt.date.fromisoformat(ref_date)
    week_sun = sun_of(ref_date)
    week_end = week_sun + dt.timedelta(days=6)
    week_key = f"{week_sun.isoformat()}_W{(week_sun.isocalendar()[1]):02d}"

    # أفضل مرشح: ملخص صوتي جاهز هذا الأسبوع ← مصدر تعلم ← مادة ILPC
    candidate = None
    digests = [d for d in S.get("audio_digests", [])
               if d.get("status") in ("DIGESTED", "NARRATED")
               and d.get("digested_at") and week_sun.isoformat() <= str(d["digested_at"])[:10] <= week_end.isoformat()]
    if digests:
        d = sorted(digests, key=lambda x: x["digested_at"])[-1]
        candidate = ("ملخص صوتي", d["title"], f"digest:{d['digest_id']}",
                     [{"branch": "النقاط الرئيسية",
                       "sub_branches": [], "leaves": (d.get("key_points") or [])[:6]}])
    if not candidate:
        learn = [l for l in S.get("learning", []) if l.get("العنوان")]
        if learn:
            l = learn[0]
            candidate = ("مصدر تعلم", l["العنوان"], f"learning:{l['العنوان']}",
                         [{"branch": "خلاصة الأسبوع", "sub_branches": [],
                           "leaves": [f"الحالة: {l.get('الحالة', '—')}",
                                      f"مرتبط بهدف: {l.get('مرتبط بهدف', '—')}"]}])
    material = os.path.join(BASE, "materials", "lp-001-lean-six-sigma-ilpc.md")
    if not candidate and os.path.exists(material):
        txt = open(material, encoding="utf-8").read()
        title, sections = parse_markdown(txt, "Lean Six Sigma — ILPC")
        candidate = ("مادة تدريبية", title, "materials/lp-001-lean-six-sigma-ilpc.md", sections)
    if not candidate:
        candidate = ("افتراضي", "خلاصة الأسبوع",
                     "لم يُسجَّل مصدر أسبوعي بعد — أضف كتابًا أو محاضرة",
                     [{"branch": "نقاط رئيسية", "sub_branches": [], "leaves": []}])

    kind, title, ref, sections = candidate
    row, created = register(title, sections, topic="weekly", source_kind=kind,
                            source_ref=ref, store=store, weekly=True,
                            week_key=week_key)
    print(f"{'✅' if created else '🔁'} الخريطة الأسبوعية {row['map_id']} — {row['title']}")
    print(f"   أسبوع: {week_sun.isoformat()} → {week_end.isoformat()} (بداية الأحد)")
    print(f"   Mermaid: reports/mindmaps/{row['file_mmd']}")
    return row, created


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "demo"
    if cmd == "demo":
        build_demo()
    elif cmd == "build":
        opts = dict(zip(args[1::2], args[2::2]))
        fpath = opts.get("--file")
        title = opts.get("--title", "خريطة ذهنية")
        if not fpath or not os.path.exists(fpath):
            print("❌ استخدم: python3 engine/mindmap.py build --title ... --file notes.md")
            raise SystemExit(1)
        txt = open(fpath, encoding="utf-8").read()
        build_from_markdown(title, txt)
    elif cmd == "weekly":
        d = None
        if "--date" in args:
            d = args[args.index("--date") + 1]
        build_weekly(d)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

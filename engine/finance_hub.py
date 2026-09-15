# -*- coding: utf-8 -*-
"""
Unified Finance Hub — v2.0 (Sep 2026)

يجعل تبويب المالية **واحدًا موحدًا** بدل تشتت قديم (finance + finance_ebsi),
ويحدّثه **تلقائيًا شهريًا** عبر لقطة شهرية، ويربطه **بشيت خارجي** لجلب المعلومات حيًا.

المبدأ:
  - **مصدر واحد:** `finance` في StateStore هو الحقيقة. `finance_ebsi` يُهاجر تلقائيًا إليه
    (النوع → عمود النوع، والقيمة → ملاحظة) ثم يُبقى للتوافق فقط.
  - **تحديث تلقائي:** كل 1 من الشهر 07:30 (عبر scheduler) + كل دورة مدير سريعة
    (throttle ساعة) يُنفذ: سحب خارجي → دمج → لقطة شهرية → تقرير.
  - **ربط شيت:** إن ضُبط `FINANCE_SHEET_ID` (أو `GOOGLE_SHEETS_WEBHOOK_URL`) يُجلب
    الجدول حيًا، وإلا يعمل محليًا فقط. لا أسرار في الكود — كلها env.

الربط الخارجي يدعم 3 مسارات حسب ما هو متاح:
  1) Webhook الآمن (Apps Script `google_sheets_webhook.gs` مع `SPREADSHEET_ID` =
     FINANCE_SHEET_ID و `AGENT_SECRET`) — الأفضل للإنتاج داخل Railway.
  2) تصدير CSV العام (`…/export?format=csv&gid=…`) إن كان الشيت مشاركًا Anyone with link.
  3) Fallback محلي: لا شيت خارجي → يعمل على `finance` فقط.

التشغيل:
  python3 engine/finance_hub.py status              ← حالة الربط واللقطات
  python3 engine/finance_hub.py sync [--force]      ← سحب ودمج الآن
  python3 engine/finance_hub.py snapshot [--force]  ← لقطة شهرية يدوية
  python3 engine/finance_hub.py link SHEET_ID [GID] ← حفظ رابط الشيت
  python3 engine/finance_hub.py unlink              ← إزالة الربط
  python3 engine/finance_hub.py report              ← تقرير مالي موحد (stdout + reports/)

يتكامل مع:
  - `engine/manager.py --loop` (throttled sync كل ساعة)
  - `engine/scheduler.py` (monthly 1st + weekly Thursday)
  - `engine/proactive.py` (SO-004/005 يقرآن `finance` الموحد نفسه)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, log_event

TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

AR_MONTHS = ["يناير","فبراير","مارس","أبريل","مايو","يونيو",
             "يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"]

# ---- env ----
def _env_sheet_id():
    return (os.environ.get("FINANCE_SHEET_ID") or "").strip()

def _env_sheet_gid():
    return (os.environ.get("FINANCE_SHEET_GID") or "").strip()

def _env_sheet_range():
    return (os.environ.get("FINANCE_SHEET_RANGE") or "").strip()  # e.g. "المالية!A1:F100"

def _env_webhook_url():
    return (os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL") or "").strip()

def _env_webhook_secret():
    return (os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET") or "").strip()

# ---- helpers ----
def _hash(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]

def _as_date(x):
    if x in (None,"", "NEEDS_INPUT"):
        return None
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except Exception:
        return None

def _parse_money(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int,float)):
        return float(v)
    s = str(v).replace(",","").replace("ريال","").replace("SAR","").strip()
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else 0.0

def _norm_header(h):
    if not h:
        return ""
    s = str(h).strip().lower()
    # Arabic + English variants
    mapping = {
        "البند": ["البند","البند ","item","name","service","البند المالي"],
        "النوع": ["النوع","type","category","الفئة"],
        "التكلفة (ريال/شهر)": ["التكلفة (ريال/شهر)","التكلفة","cost","amount","ريال/شهر","monthly","price","التكلفة الشهرية"],
        "تاريخ التجديد": ["تاريخ التجديد","renew","renewal","due","تاريخ الاستحقاق","تجديد"],
        "آخر استخدام": ["آخر استخدام","last use","last_used","استخدام","last","آخر_استخدام"],
        "ملاحظة": ["ملاحظة","note","notes","ملاحظات","comment"],
    }
    for canonical, variants in mapping.items():
        for v in variants:
            if v in s or s in v:
                return canonical
    return str(h).strip()

# ---- external fetch ----
def _fetch_via_webhook(sheet_id: str) -> list[dict] | None:
    url = _env_webhook_url()
    secret = _env_webhook_secret()
    if not url or not secret or not sheet_id:
        return None
    try:
        payload = json.dumps({"secret": secret, "action": "snapshot", "maxRows": 150, "maxCols": 16}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok") or "data" not in data:
            return None
        # Find finance-like sheet
        sheets = data["data"]
        # Prefer sheet named مالية / Finance / Financial_Restructuring
        cand_names = ["مالية","المالية","Finance","Financial_Restructuring","Financial","finance","FINANCE"]
        target = None
        for n in cand_names:
            if n in sheets:
                target = sheets[n]
                break
        if not target:
            # fallback: any sheet with finance-like header
            for name, rows in sheets.items():
                if rows and any("البند" in str(c) or "cost" in str(c).lower() for c in rows[0]):
                    target = rows
                    break
        if not target or len(target) < 2:
            return None
        headers = [_norm_header(h) for h in target[0]]
        out=[]
        for r in target[1:]:
            if not any(c for c in r):
                continue
            row={}
            for h, v in zip(headers, r):
                if h:
                    row[h]=v
            if row.get("البند"):
                out.append(row)
        return out
    except Exception as exc:
        log_event("finance_fetch_webhook_error", error=str(exc)[:160])
        return None

def _fetch_via_csv(sheet_id: str, gid: str = "") -> list[dict] | None:
    if not sheet_id:
        return None
    try:
        # Use export CSV; gid optional
        base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        if gid:
            base += f"&gid={gid}"
        # Some sheets need range; we fetch full
        with urllib.request.urlopen(base, timeout=12) as resp:
            text = resp.read().decode("utf-8-sig")
        import csv, io
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows or len(rows) < 2:
            return None
        headers = [_norm_header(h) for h in rows[0]]
        out=[]
        for r in rows[1:]:
            if not any(c.strip() for c in r if c):
                continue
            row={}
            for h, v in zip(headers, r):
                if h:
                    row[h]=v
            if row.get("البند"):
                out.append(row)
        return out if out else None
    except Exception as exc:
        log_event("finance_fetch_csv_error", error=str(exc)[:160])
        return None

def _fetch_via_local_file() -> list[dict] | None:
    """Fallback: user's manual export dropped in data/ — supports offline linking."""
    for fname in ["finance-external.csv", "finance-link.csv", "finance_external.csv"]:
        path = os.path.join(BASE, "data", fname)
        if not os.path.exists(path):
            continue
        try:
            import csv
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows or len(rows) < 2:
                continue
            headers = [_norm_header(h) for h in rows[0]]
            out=[]
            for r in rows[1:]:
                if not any(c.strip() for c in r if c):
                    continue
                row={}
                for h, v in zip(headers, r):
                    if h:
                        row[h]=v
                if row.get("البند"):
                    out.append(row)
            if out:
                log_event("finance_fetch_local", file=fname, rows=len(out))
                return out
        except Exception as exc:
            log_event("finance_fetch_local_error", error=str(exc)[:160])
    return None

def fetch_external_finance() -> tuple[list[dict] | None, str]:
    """
    Returns (rows|None, source). source in {"webhook","csv","local_file","none","disabled"}.
    Resolves sheet_id from env or from stored link in state.
    """
    store = Store()
    S = store.rows_all()
    # stored link overrides env if env not set
    links = S.get("finance_links", [])
    stored = links[0] if links else {}
    sheet_id = _env_sheet_id() or stored.get("sheet_id") or ""
    gid = _env_sheet_gid() or stored.get("gid") or ""
    if not sheet_id:
        # Check local file fallback even without sheet_id
        rows = _fetch_via_local_file()
        if rows is not None:
            return rows, "local_file"
        return None, "disabled"

    # Try webhook first (secure)
    rows = _fetch_via_webhook(sheet_id)
    if rows is not None:
        return rows, "webhook"
    # Try CSV (public)
    rows = _fetch_via_csv(sheet_id, gid)
    if rows is not None:
        return rows, "csv"
    # Try local file as offline fallback
    rows = _fetch_via_local_file()
    if rows is not None:
        return rows, "local_file"
    return None, "none"

def normalize_finance_row(raw: dict) -> dict:
    """Map any external row to internal finance schema."""
    cost = _parse_money(raw.get("التكلفة (ريال/شهر)") or raw.get("التكلفة") or raw.get("cost") or 0)
    # Dates: try parse
    renew = raw.get("تاريخ التجديد")
    last = raw.get("آخر استخدام")
    # Normalize dates to iso
    def norm_d(v):
        d = _as_date(v)
        return d.isoformat() if d else (str(v).strip() if v else None)
    return {
        "البند": str(raw.get("البند") or raw.get("item") or "").strip(),
        "النوع": str(raw.get("النوع") or "عام").strip() or "عام",
        "التكلفة (ريال/شهر)": cost,
        "تاريخ التجديد": norm_d(renew),
        "آخر استخدام": norm_d(last),
        "ملاحظة": str(raw.get("ملاحظة") or raw.get("note") or "").strip() or None,
        "المصدر": raw.get("_source") or "external" if raw.get("_external") else "local",
    }

# ---- unify ----
def _dedup_key(row):
    return re.sub(r"\s+", " ", str(row.get("البند") or "").strip().lower())

def unify_finance(local_rows: list[dict], external_rows: list[dict] | None) -> tuple[list[dict], dict]:
    """
    Merge local + external. External wins on conflict by newer renewal/last_use,
    but never deletes local rows (adds missing). Returns (merged, stats).
    """
    merged = {}
    for r in local_rows:
        k = _dedup_key(r)
        if k:
            merged[k] = dict(r)
            merged[k]["_origin"] = "local"
    stats = {"local": len(merged), "external": 0, "added":0, "updated":0, "kept":0}
    if external_rows:
        stats["external"] = len(external_rows)
        for raw in external_rows:
            norm = normalize_finance_row({**raw, "_external": True})
            k = _dedup_key(norm)
            if not k:
                continue
            if k not in merged:
                merged[k] = norm
                merged[k]["ملاحظة"] = (norm.get("ملاحظة") or "") + " ↻ من الشيت الخارجي"
                stats["added"] += 1
            else:
                # Update if external has more recent dates or fills empty
                cur = merged[k]
                # Prefer external if it has renewal and local doesn't, or external renewal is later
                ext_renew = _as_date(norm.get("تاريخ التجديد"))
                cur_renew = _as_date(cur.get("تاريخ التجديد"))
                ext_last = _as_date(norm.get("آخر استخدام"))
                cur_last = _as_date(cur.get("آخر استخدام"))
                updated=False
                if ext_renew and (not cur_renew or ext_renew != cur_renew):
                    cur["تاريخ التجديد"] = norm["تاريخ التجديد"]
                    updated=True
                if ext_last and (not cur_last or ext_last > cur_last):
                    cur["آخر استخدام"] = norm["آخر استخدام"]
                    updated=True
                if norm.get("التكلفة (ريال/شهر)") and norm["التكلفة (ريال/شهر)"] != cur.get("التكلفة (ريال/شهر)"):
                    cur["التكلفة (ريال/شهر)"] = norm["التكلفة (ريال/شهر)"]
                    updated=True
                if updated:
                    cur["ملاحظة"] = (cur.get("ملاحظة") or "") + " ↻ حدّث من الخارج"
                    stats["updated"] += 1
                else:
                    stats["kept"] += 1
    # Back to list, sorted by renewal date then name
    out = sorted(merged.values(), key=lambda r: (str(r.get("تاريخ التجديد") or "9999"), str(r.get("البند"))))
    # Clean temp
    for r in out:
        r.pop("_origin", None)
        r.pop("_source", None)
    return out, stats

def migrate_ebsi_if_needed(S: dict) -> bool:
    """One-time: move finance_ebsi rows into finance if finance_ebsi non-empty and finance missing them."""
    ebsi = S.get("finance_ebsi", [])
    if not ebsi:
        return False
    # ebsi expected shape: list of dicts with item/monthly etc or generic
    # Keep simple: if ebsi rows have no counterpart in finance by name, add them
    finance = S.get("finance", [])
    existing = {_dedup_key(r) for r in finance}
    added=0
    for e in ebsi:
        # Try common keys
        name = e.get("item") or e.get("البند") or e.get("name") or ""
        if not name:
            continue
        k = _dedup_key({"البند": name})
        if k in existing:
            continue
        cost = _parse_money(e.get("monthly") or e.get("التكلفة (ريال/شهر)") or e.get("amount") or 0)
        finance.append({
            "البند": str(name),
            "النوع": str(e.get("type") or e.get("النوع") or "EBSI-مُهاجر"),
            "التكلفة (ريال/شهر)": cost,
            "تاريخ التجديد": e.get("تاريخ التجديد"),
            "آخر استخدام": e.get("آخر استخدام"),
            "ملاحظة": f"مُهاجر من finance_ebsi · {e.get('note') or ''}".strip(" ·"),
        })
        added+=1
    if added:
        S["finance"] = finance
        log_event("finance_ebsi_migrated", added=added)
        return True
    return False

# ---- monthly snapshot ----
def _snapshot_id(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

def build_snapshot(S: dict, ref: dt.date | None = None) -> dict:
    ref = ref or dt.date.today()
    sid = _snapshot_id(ref)
    rows = S.get("finance", [])
    total = sum(_parse_money(r.get("التكلفة (ريال/شهر)")) for r in rows)
    by_type = {}
    for r in rows:
        t = str(r.get("النوع") or "عام")
        by_type[t] = by_type.get(t, 0) + _parse_money(r.get("التكلفة (ريال/شهر)"))
    unused = [r for r in rows if _as_date(r.get("آخر استخدام")) and (ref - _as_date(r["آخر استخدام"])).days > 30]
    renew30 = [r for r in rows if _as_date(r.get("تاريخ التجديد")) and 0 <= (_as_date(r["تاريخ التجديد"]) - ref).days <= 30]
    # EBSI-like health index (same as scheduler)
    unused_n = len(unused)
    savings = sum(_parse_money(r.get("التكلفة (ريال/شهر)")) for r in unused)
    base=100
    if total>0:
        base -= min(20, unused_n*5)
        if unused_n:
            base-=5
    index=max(0, base)
    # Find external source label
    links = S.get("finance_links", [])
    source = links[0].get("sheet_id","local") if links else "local"
    return {
        "snapshot_id": sid,
        "date": ref.isoformat(),
        "total_monthly": total,
        "total_yearly": total*12,
        "by_type": by_type,
        "rows_count": len(rows),
        "unused_count": unused_n,
        "savings_potential": savings,
        "renew30": [{"البند": r["البند"], "تاريخ التجديد": r["تاريخ التجديد"], "التكلفة": r["التكلفة (ريال/شهر)"]} for r in renew30],
        "unused": [{"البند": r["البند"], "آخر استخدام": r["آخر استخدام"], "التكلفة": r["التكلفة (ريال/شهر)"]} for r in unused],
        "health_index": index,
        "source": source,
    }

def render_monthly_report(snapshot: dict, finance_rows: list[dict]) -> str:
    d = dt.date.fromisoformat(snapshot["date"])
    title = f"# 💰 التقرير المالي الموحد — {AR_MONTHS[d.month-1]} {d.year} ({snapshot['snapshot_id']})"
    lines=[title,"", f"> **مصدر واحد موحد** — `finance` في StateStore (يُحدَّث تلقائيًا كل 1 من الشهر + عند توفر شيت خارجي)."]
    lines+=["", f"- إجمالي الالتزامات الشهرية: **{snapshot['total_monthly']:,.0f} ريال** ({snapshot['total_yearly']:,.0f} ريال/سنة)"]
    lines+= [f"- عدد البنود: **{snapshot['rows_count']}** | بنود غير مستخدمة >30يوم: **{snapshot['unused_count']}** (وفورات محتملة **{snapshot['savings_potential']:,.0f} ريال/شهر**)"]
    lines+= [f"- مؤشر الصحة المالية: **{snapshot['health_index']}/100**"]
    lines+= [f"- مصدر الربط: `{snapshot['source']}`"]
    lines+= ["", "## 📊 حسب النوع"]
    for t, v in sorted(snapshot["by_type"].items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {v:,.0f} ريال/شهر ({v*12:,.0f}/سنة)")
    if snapshot["renew30"]:
        lines+= ["", "## 🔁 تجديدات خلال 30 يومًا"]
        for r in snapshot["renew30"]:
            lines.append(f"- {r['البند']} — {r['تاريخ التجديد']} — {r['التكلفة']:,.0f} ريال")
    if snapshot["unused"]:
        lines+= ["", "## ⚠️ بنود غير مستخدمة (مرشحة للإلغاء/التفاوض)"]
        for r in snapshot["unused"]:
            lines.append(f"- {r['البند']} — آخر استخدام {r['آخر استخدام']} — {r['التكلفة']:,.0f} ريال/شهر")
    lines+= ["", "## 📋 السجل الكامل (finance الموحد)"]
    lines+= ["| البند | النوع | ريال/شهر | تجديد | آخر استخدام | ملاحظة |"]
    lines+= ["|---|---|---:|---|---|---|"]
    for r in finance_rows:
        lines.append(f"| {r.get('البند','')} | {r.get('النوع','')} | { _parse_money(r.get('التكلفة (ريال/شهر)')):,.0f} | {r.get('تاريخ التجديد') or '—'} | {r.get('آخر استخدام') or '—'} | {r.get('ملاحظة') or ''} |")
    lines+= ["", f"_تاريخ التقرير: {snapshot['date']} — يُحدَّث تلقائيًا. للربط: `python3 engine/finance_hub.py link SHEET_ID [GID]`_"]
    return "\n".join(lines)

# ---- public API ----
def sync_external(store: Store | None = None, force: bool = False) -> dict:
    """Pull external sheet and unify into finance. Returns stats."""
    store = store or Store()
    # throttle: once per hour unless force
    S_tmp = store.rows_all()
    last = (S_tmp.get("manager_markers") or {}).get("finance_last_sync")
    if not force and last:
        try:
            last_dt = dt.datetime.fromisoformat(last.replace("Z","").replace(" ","T"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=TZ)
            if (dt.datetime.now(TZ) - last_dt).total_seconds() < 3600:
                return {"skipped":"throttled", "last": last}
        except Exception:
            pass
    ext_rows, src = fetch_external_finance()
    def mutate(S):
        changed=False
        # migrate ebsi first (once)
        if migrate_ebsi_if_needed(S):
            changed=True
        local = S.get("finance", [])
        merged, stats = unify_finance(local, ext_rows)
        # Detect real change via hash (handle dates)
        if json.dumps(merged, sort_keys=True, ensure_ascii=False, default=str) != json.dumps(local, sort_keys=True, ensure_ascii=False, default=str):
            S["finance"] = merged
            changed=True
        # Update markers
        markers=dict(S.get("manager_markers") or {})
        markers["finance_last_sync"] = dt.datetime.now(TZ).isoformat(timespec="seconds")
        markers["finance_last_source"] = src
        markers["finance_external_rows"] = len(ext_rows) if ext_rows else 0
        S["manager_markers"]=markers
        if changed:
            stats["changed"]=True
        else:
            stats["changed"]=False
        stats["source"]=src
        return changed, stats
    result = store.transaction(mutate, "finance_sync", source=src)
    log_event("finance_sync", source=src, result=result)
    return result

def ensure_monthly_snapshot(store: Store | None = None, ref: dt.date | None = None, force: bool = False) -> dict | None:
    store = store or Store()
    ref = ref or dt.date.today()
    sid = _snapshot_id(ref)
    S = store.rows_all()
    snaps = S.get("finance_snapshots", [])
    if not force and any(s.get("snapshot_id")==sid for s in snaps):
        return None  # already
    snapshot = build_snapshot(S, ref)
    # Render report
    report = render_monthly_report(snapshot, S.get("finance", []))
    path = os.path.join(REPORTS, f"finance-monthly-{sid}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    # Also HTML quick
    html_path = os.path.join(REPORTS, f"finance-monthly-{sid}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f"<html dir='rtl' lang='ar'><meta charset='utf-8'><pre style='font-family:system-ui;white-space:pre-wrap'>{report}</pre></html>")
    def mutate(S):
        snaps = [s for s in S.get("finance_snapshots", []) if s.get("snapshot_id")!=sid]
        snaps.append(snapshot)
        snaps = sorted(snaps, key=lambda x: x["snapshot_id"])[-24:]  # keep 24 months
        S["finance_snapshots"]=snaps
        # Also ensure links section exists
        S.setdefault("finance_links", S.get("finance_links") or [])
        return True, {"snapshot_id": sid, "path": os.path.relpath(path, BASE), "total": snapshot["total_monthly"]}
    result = store.transaction(mutate, "finance_snapshot", snapshot=sid)
    log_event("finance_snapshot", snapshot=sid, total=snapshot["total_monthly"])
    return {"snapshot": snapshot, "report": os.path.relpath(path, BASE), **result}

def auto_update(store: Store | None = None, ref: dt.datetime | None = None, force: bool = False) -> dict:
    """Called from scheduler/manager: sync + snapshot if due (1st of month)."""
    store = store or Store()
    ref = ref or dt.datetime.now(TZ)
    d = ref.date()
    sync_res = sync_external(store, force=force)
    snap_res=None
    # Snapshot due on day 1, or if no snapshot for this month yet and it's past day 1
    sid = _snapshot_id(d)
    S = store.rows_all()
    has = any(s.get("snapshot_id")==sid for s in S.get("finance_snapshots", []))
    if force or d.day == 1 or (d.day>1 and not has):
        snap_res = ensure_monthly_snapshot(store, ref=d, force=force)
    return {"sync": sync_res, "snapshot": snap_res, "date": d.isoformat()}

def link_sheet(sheet_id: str, gid: str = "", store: Store | None = None) -> dict:
    store = store or Store()
    if not sheet_id or len(sheet_id) < 10:
        raise ValueError("SHEET_ID غير صالح")
    def mutate(S):
        S["finance_links"]=[{"sheet_id": sheet_id.strip(), "gid": gid.strip(), "linked_at": dt.datetime.now(TZ).isoformat(timespec="seconds"), "by": "finance_hub"}]
        markers=dict(S.get("manager_markers") or {})
        markers["finance_link_sheet"] = sheet_id.strip()
        S["manager_markers"]=markers
        return True, {"sheet_id": sheet_id.strip(), "gid": gid.strip()}
    res = store.transaction(mutate, "finance_link", sheet_id=sheet_id.strip())
    log_event("finance_link", sheet_id=sheet_id.strip(), gid=gid.strip())
    return res

def unlink_sheet(store: Store | None = None) -> bool:
    store = store or Store()
    def mutate(S):
        if not S.get("finance_links"):
            return False, False
        S["finance_links"]=[]
        markers=dict(S.get("manager_markers") or {})
        markers.pop("finance_link_sheet", None)
        S["manager_markers"]=markers
        return True, True
    res = store.transaction(mutate, "finance_unlink")
    log_event("finance_unlink")
    return res

def status(store: Store | None = None) -> dict:
    store = store or Store()
    S = store.rows_all()
    finance = S.get("finance", [])
    snaps = S.get("finance_snapshots", [])
    links = S.get("finance_links", [])
    markers = S.get("manager_markers") or {}
    # Try fetch dry (no write)
    ext_rows, src = fetch_external_finance()
    total = sum(_parse_money(r.get("التكلفة (ريال/شهر)")) for r in finance)
    hint=None
    if src == "none" and (links or _env_sheet_id()):
        # Sheet linked but not reachable — explain
        if not _env_webhook_url() or not _env_webhook_secret():
            hint = "الشيت مربوط لكن CSV محظور/خاص — اجعل الشيت Anyone with link أو اضبط GOOGLE_SHEETS_WEBHOOK_URL + SECRET، أو ضع ملف data/finance-external.csv يدويًا"
        else:
            hint = "Webhook مضبوط لكن فشل الجلب — تأكد من SPREADSHEET_ID و AGENT_SECRET في Apps Script"
    elif src == "disabled":
        hint = "لا رابط خارجي — يعمل محليًا فقط. اربط شيتًا: python3 engine/finance_hub.py link SHEET_ID"
    elif src == "local_file":
        hint = "يُستخدم ملف محلي data/finance-external.csv — حدّث الملف يدويًا أو انتقل للـ Webhook"
    return {
        "finance_rows": len(finance),
        "total_monthly": total,
        "total_yearly": total*12,
        "snapshots": len(snaps),
        "latest_snapshot": snaps[-1]["snapshot_id"] if snaps else None,
        "link": links[0] if links else None,
        "env_sheet_id": _env_sheet_id() or None,
        "webhook_configured": bool(_env_webhook_url() and _env_webhook_secret()),
        "external_preview_rows": len(ext_rows) if ext_rows else 0,
        "external_source": src,
        "last_sync": markers.get("finance_last_sync"),
        "last_source": markers.get("finance_last_source"),
        "health_index": build_snapshot(S)["health_index"] if finance else None,
        "hint": hint,
    }

# ---- CLI ----
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Unified Finance Hub")
    ap.add_argument("cmd", choices=["status","sync","snapshot","link","unlink","report","auto"], nargs="?", default="status")
    ap.add_argument("arg1", nargs="?")
    ap.add_argument("arg2", nargs="?")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    try:
        if args.cmd == "status":
            print(json.dumps(status(), ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "sync":
            res = sync_external(force=args.force)
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
            if res.get("changed"):
                print("✅ finance موحد — تم الدمج")
            else:
                print("ℹ️ لا تغيير")
        elif args.cmd == "snapshot":
            ref = dt.date.today()
            res = ensure_monthly_snapshot(ref=ref, force=args.force)
            if res:
                print(f"✅ لقطة شهرية: {res['report']} — {res['snapshot']['total_monthly']:,.0f} ريال/شهر")
            else:
                print("ℹ️ اللقطة موجودة مسبقًا (استخدم --force لإعادة)")
        elif args.cmd == "link":
            if not args.arg1:
                print("الاستخدام: python3 engine/finance_hub.py link SHEET_ID [GID]")
                sys.exit(1)
            res = link_sheet(args.arg1, args.arg2 or "")
            print(f"✅ رُبط الشيت: {res['sheet_id']} gid={res['gid']}")
        elif args.cmd == "unlink":
            unlink_sheet()
            print("✅ أُزيل الربط")
        elif args.cmd == "report":
            S = Store().rows_all()
            snap = build_snapshot(S)
            print(render_monthly_report(snap, S.get("finance", [])))
        elif args.cmd == "auto":
            res = auto_update(force=args.force)
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()

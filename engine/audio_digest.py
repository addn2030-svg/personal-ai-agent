# -*- coding: utf-8 -*-
"""
خط إنتاج الملخصات المسموعة (Audio Digests) — v0.9.

الوكيل المعرفي (Knowledge & Audio Agent) يستقبل رابط فيديو/كتاب/محاضرة، فيُنشئ
ملخصًا منظمًا يتحول إلى:
  1) 🗺️ خريطة ذهنية (عبر engine/mindmap.py)
  2) 📄 نص الملخص + سكربت سردي 5–7 دقائق (reports/audio_digests/)
  3) 🔊 ملف صوتي عند توفر مزوّد TTS عبر متغيرات البيئة فقط
     (ELEVENLABS_API_KEY — لا مفتاح في المستودع أبدًا)

آلة الحالة: QUEUED ← new · DIGESTED ← جاهز (خريطة + سكربت) · NARRATED ← ملف صوتي.

التشغيل:
  python3 engine/audio_digest.py queue --title "مفهوم Mulligan NKT" \\
        --kind lecture --url https://youtu.be/... [--notes-file digest-notes.md]
  python3 engine/audio_digest.py process --all            ← يبني الخرائط والسكربتات
  python3 engine/audio_digest.py script AD-001            ← عرض السكربت السردي
  python3 engine/audio_digest.py render-audio AD-001      ← توليد mp3 عبر المزوّد (اختياري)
  python3 engine/audio_digest.py list

يُسجَّل كل عنصر في قسم audio_digests بمخزن الحالة؛ لا يُرسل أي شيء خارجيًا
دون مرور عبر طابور الاعتماد (من scheduler.py).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mindmap
from store import Store, log_event

REPORTS = os.path.join(BASE, "reports")
DIGEST_DIR = os.path.join(REPORTS, "audio_digests")
os.makedirs(DIGEST_DIR, exist_ok=True)

VALID_KINDS = {"youtube", "book", "lecture", "article", "podcast"}
TOPIC_BY_KIND = {"youtube": "knowledge", "book": "book", "lecture": "clinical",
                 "article": "knowledge", "podcast": "knowledge"}


def _next_digest_id(S):
    used = {int(m["digest_id"].split("-")[1]) for m in S.get("audio_digests", [])
            if m.get("digest_id", "").startswith("AD-")}
    n = 1
    while n in used:
        n += 1
    return f"AD-{n:03d}"


def queue(title, source_kind, source_url="", note="", notes_file="", store=None):
    """إدراج مصدر جديد في الطابور (idempotent برابط/عنوان)."""
    store = store or Store()
    if source_kind not in VALID_KINDS:
        raise SystemExit(f"❌ النوع يجب أن يكون أحد: {sorted(VALID_KINDS)}")
    if notes_file:
        if not os.path.exists(notes_file):
            raise SystemExit(f"❌ الملف غير موجود: {notes_file}")
        note = open(notes_file, encoding="utf-8").read()
    key = (source_url or title).strip().lower()
    S = store.rows_all()
    dupe = next((d for d in S.get("audio_digests", [])
                 if (d.get("source_url") or d.get("title", "")).strip().lower() == key),
                None)
    if dupe:
        print(f"🔁 موجود أصلًا: {dupe['digest_id']} — {dupe['title']} ({dupe['status']})")
        return dupe
    row = {
        "digest_id": _next_digest_id(S),
        "title": title,
        "source_kind": source_kind,
        "source_url": source_url,
        "note": note[:4000],
        "status": "QUEUED",
        "queued_at": dt.date.today().isoformat(),
        "digested_at": None,
        "key_points": [],
        "action_items": [],
        "narrator_script": "",
        "map_id": None,
        "audio_path": None,
        "provider": None,
    }
    S["audio_digests"].append(row)
    store.commit(S, "audio_digest_queue", digest_id=row["digest_id"])
    log_event("audio_digest_queued", digest_id=row["digest_id"], title=title)
    print(f"✅ {row['digest_id']} في الطابور: {title} — شغّل process لبناء الخريطة والسكربت")
    return row


def _split_points(text):
    """استخراج نقاط رئيسية من نص ملخص (سطور نقطية/مرقمة فقط) أو نص حر."""
    if not text:
        return []
    heading_re = re.compile(r"^#{1,6}\s+")
    bullet_re = re.compile(r"^[-*•\u2022\d.)\[]+\s*(.*)$")
    points = []
    for line in text.splitlines():
        line = line.strip()
        if not line or heading_re.match(line):  # عناوين ## لا تُعد نقاطًا
            continue
        m = bullet_re.match(line)
        if m:
            clean = m.group(1).strip()
            if len(clean) >= 6:
                points.append(clean)
        elif len(line) >= 24:
            points.append(line)  # نص حر: جملة كاملة
    if len(points) >= 3:
        return points[:7]
    # نص حر بدون نقاط: نأخذ الجمل الأولى
    sentences = re.split(r"[.!؟]\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20][:5]


def process(digest_id=None, all_items=False, store=None):
    """بناء خريطة ذهنية + نص ملخص + سكربت سردي لكل عنصر QUEUED.

    تُنفَّذ كل خطوة كمعاملة مستقلة (mindmap.register ثم تحديث صف الملخص)
    لتجنب أي تعارض كتابة متداخل مع مخزن الحالة.
    """
    store = store or Store()
    S = store.rows_all()
    items = S.get("audio_digests", [])
    if digest_id:
        ids = [x["digest_id"] for x in items if x["digest_id"] == digest_id]
        if not ids:
            raise SystemExit(f"❌ لا يوجد ملخص {digest_id}")
    elif all_items:
        ids = [x["digest_id"] for x in items if x.get("status") == "QUEUED"]
    else:
        raise SystemExit("❌ حدد المعرّف أو استخدم --all")
    if not ids:
        print("🔁 لا عناصر QUEUED للمعالجة.")
        return []

    done = []
    for did in ids:
        fresh = store.rows_all()
        d = next((x for x in fresh.get("audio_digests", [])
                  if x["digest_id"] == did and x.get("status") == "QUEUED"), None)
        if d is None:
            continue  # عولجت للتو في تشغيل موازٍ — تخطٍّ آمن
        points = _split_points(d.get("note") or "")
        if not points:
            points = [f"ملخص أولي: {d['title']} — أضف النقاط من التفريغ لاحقًا"]
        sections = [{"branch": "النقاط الرئيسية", "sub_branches": [], "leaves": points},
                    {"branch": "خطوات مقترحة", "sub_branches": [],
                     "leaves": d.get("action_items") or
                     ["الاستماع الكامل للمصدر الأصلي", "تطبيق فكرة واحدة هذا الأسبوع"]}]
        title = d["title"]
        if len(title) > 60:
            title = title[:57] + "…"
        # 1) الخريطة الذهنية — معاملة مستقلة (مسؤولة عن ملفاتها وتسجيلها)
        map_row, _created = mindmap.register(
            title, sections, topic=TOPIC_BY_KIND.get(d["source_kind"], "knowledge"),
            source_kind=f"audio-digest:{d['source_kind']}",
            source_ref=d.get("source_url") or d["digest_id"], store=store,
            digest_id=did)
        # 2) تحديث صف الملخص — معاملة مستقلة
        def _change(S):
            row = next((x for x in S.get("audio_digests", [])
                        if x["digest_id"] == did), None)
            if not row or row.get("status") != "QUEUED":
                return False, None
            row.update({
                "status": "DIGESTED",
                "digested_at": dt.date.today().isoformat(),
                "key_points": points,
                "map_id": map_row["map_id"],
                "narrator_script": build_script({**row, "key_points": points},
                                                map_row),
            })
            return True, row

        updated = store.transaction(_change, "audio_digest_processed",
                                    digest_id=did, map_id=map_row["map_id"])
        if updated is None:
            continue
        _save_digest_report(updated, map_row)
        log_event("audio_digest_digested", digest_id=did,
                  map_id=map_row["map_id"], points=len(points))
        print(f"✅ {did} DIGESTED — {updated['title']} (خريطة {map_row['map_id']})")
        done.append(updated)
    return done


def build_script(d, map_row):
    """سكربت سردي 5–7 دقائق (بنية حتمية تُستبدل لاحقًا بنص LLM عند توفره)."""
    lines = [
        f"السلام عليكم، معكم عبدالرحمن في ملخص اليوم من النظام.",
        f"العنوان: {d['title']}.",
        "أبرز النقاط:",
    ]
    for i, p in enumerate(d.get("key_points", [])[:5], 1):
        lines.append(f"النقطة {i}: {p}")
    lines += [
        "الخطوة المقترحة اليوم: اختر فكرة واحدة فقط من هذه النقاط وطبّقها.",
        "شكرًا لاستماعكم، وإلى ملخص جديد غدًا إن شاء الله.",
    ]
    return "\n".join(lines)


def _save_digest_report(d, map_row):
    """تقرير الملخص (md + سكربت) في reports/audio_digests/."""
    md = f"""# 🎧 {d['title']}

> ملخص صوتي {d['digest_id']} — المصدر: {d.get('source_url') or d.get('source_kind')}
> الحالة: {d['status']} | أُنشئ: {d['digested_at'] or d['queued_at']}
> الخريطة الذهنية: reports/mindmaps/{map_row['file_md']}

## 🗺️ الخريطة الذهنية المرتبطة
{MAP_HINT}

## 📌 النقاط الرئيسية
""" + "\n".join(f"- {p}" for p in d.get("key_points", [])) + f"""

## 🎙️ السكربت السردي (5–7 دقائق)

```text
{d['narrator_script']}
```

## ⚡ خطوات مقترحة
""" + "\n".join(f"- {a}" for a in (d.get("action_items") or
                                    ["الاستماع للمصدر الأصلي", "تطبيق فكرة واحدة"])) + "\n"
    out = os.path.join(DIGEST_DIR, f"{d['digest_id'].lower()}-report.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    return out


MAP_HINT = "عرض الكود في mermaid.live أو Obsidian — مسار الملف: أنظر الأعلى."


def render_audio(digest_id, store=None):
    """توليد mp3 عبر مزوّد TTS (متغيرات بيئة فقط) أو توجيه واضح إن لم يُهيّأ."""
    store = store or Store()
    S = store.rows_all()
    d = next((x for x in S.get("audio_digests", []) if x["digest_id"] == digest_id), None)
    if not d:
        raise SystemExit(f"❌ لا يوجد {digest_id}")
    if d.get("status") not in ("DIGESTED", "NARRATED"):
        raise SystemExit(f"❌ {digest_id} بحالة {d['status']} — شغّل process أولًا.")
    script = d.get("narrator_script") or build_script(d, {})
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    out_path = os.path.join(DIGEST_DIR, f"{digest_id.lower()}-narration.mp3")
    if not api_key:
        # لا شبكة ولا مفاتيح: نجّهز كل شيء ونتوقف عند السكربت
        scr = os.path.join(DIGEST_DIR, f"{digest_id.lower()}-script.md")
        with open(scr, "w", encoding="utf-8") as fh:
            fh.write(f"# 🎙️ سكربت {digest_id}\n\n```text\n{script}\n```\n")
        print("🔇 لا يوجد ELEVENLABS_API_KEY في البيئة — لن أرسل النص لأي خدمة خارجية.")
        print(f"   السكربت السردي جاهز: reports/audio_digests/{os.path.basename(scr)}")
        print("   لتوليد الصوت: عرّف ELEVENLABS_API_KEY (واختياريًا ELEVENLABS_VOICE_ID)")
        print("   ثم أعد الأمر نفسه.")
        return None
    # هنا فقط يوجد مفتاح بيئة حقيقي — استدعاء ElevenLabs TTS
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        req = urllib.request.Request(url, data=json.dumps({
            "text": script, "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode(), headers={"Content-Type": "application/json",
                              "xi-api-key": api_key})
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
        with open(out_path, "wb") as fh:
            fh.write(data)
        d["audio_path"] = os.path.relpath(out_path, BASE)
        d["provider"] = "elevenlabs"
        d["status"] = "NARRATED"
        store.commit(store.rows_all(), "audio_digest_narrated", digest_id=digest_id)
        log_event("audio_digest_narrated", digest_id=digest_id)
        print(f"✅ ملف صوتي → reports/audio_digests/{os.path.basename(out_path)}")
        return out_path
    except Exception as exc:  # noqa: BLE001
        log_event("audio_digest_tts_error", digest_id=digest_id, error=str(exc)[:160])
        print(f"❌ فشل التوليد عبر ElevenLabs: {exc}")
        return None


def script(digest_id, store=None):
    store = store or Store()
    d = next((x for x in store.rows_all().get("audio_digests", [])
              if x["digest_id"] == digest_id), None)
    if not d:
        raise SystemExit(f"❌ لا يوجد {digest_id}")
    print(f"\n🎙️ سكربت {digest_id} — {d['title']} (5–7 دقائق)\n" + "=" * 40)
    print(d.get("narrator_script") or build_script(d, {}))
    print("=" * 40)


def list_digests(store=None):
    store = store or Store()
    rows = store.rows_all().get("audio_digests", [])
    if not rows:
        print("لا ملخصات بعد — استخدم queue لإضافة مصدر.")
        return
    for d in rows:
        print(f"{d['digest_id']}  [{d['status']}]  {d['title']}  "
              f"(خريطة {d.get('map_id') or '—'})")
    return rows


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "list"

    def get(name, default=""):
        return args[args.index(name) + 1] if name in args else default

    if cmd == "queue":
        queue(get("--title"), get("--kind", "youtube"), get("--url"),
              get("--note"), get("--notes-file"))
    elif cmd == "process":
        if "--all" in args:
            process(all_items=True)
        else:
            pid = next((a for a in args[1:] if not a.startswith("--")), None)
            if not pid:
                raise SystemExit("❌ حدد معرّف الملخص أو استخدم --all")
            process(digest_id=pid)
    elif cmd == "script":
        script(args[1] if len(args) > 1 else "")
    elif cmd == "render-audio":
        render_audio(args[1] if len(args) > 1 else "")
    elif cmd == "list":
        list_digests()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""نسخة احتياطية كاملة للمستودع إلى Supabase Storage (bucket repo-backups).

الاستخدام:
  python3 scripts/repo_backup.py            # نسخة كاملة (tar.gz من git — يحترم .gitignore)
  python3 scripts/repo_backup.py --list     # آخر النسخ

المتغيرات: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (service_role فقط —
bucket خاص). Bucket `repo-backups` يُنشأ تلقائيًا أول مرة.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
BUCKET = os.environ.get("SUPABASE_BACKUP_BUCKET", "repo-backups")
STORAGE_PATH = "personal-ai-agent"


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
           or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL و SUPABASE_SERVICE_ROLE_KEY مطلوبان")
    return url, key


def _req(url, *, method="GET", key=None, data=None, headers=None):
    h = dict(headers or {})
    if key:
        h["Authorization"] = "Bearer " + key
    return urllib.request.urlopen(urllib.request.Request(url, method=method, data=data, headers=h), timeout=120)


def ensure_bucket(url: str, key: str) -> None:
    try:
        _req(f"{url}/storage/v1/bucket/{BUCKET}", method="HEAD", key=key)
        return  # موجود
    except urllib.error.HTTPError:
        pass
    body = json.dumps({"name": BUCKET, "public": False}).encode()
    try:
        _req(f"{url}/storage/v1/bucket", method="POST", key=key, data=body,
             headers={"Content-Type": "application/json"})
        print(f"repo-backup: bucket `{BUCKET}` created", flush=True)
    except urllib.error.HTTPError as e:
        if e.code != 409:
            raise


def make_archive() -> bytes:
    """tar.gz للمستودع من git نفسه (نظيف ويحترم .gitignore تلقائيًا)."""
    out = subprocess.run(["git", "-C", str(BASE), "archive", "--format=tar.gz", "HEAD"],
                         capture_output=True, check=True)
    return out.stdout


def push_backup(url: str, key: str, payload: bytes, tag: str) -> str:
    ts = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime("%Y%m%d-%H%M%S")
    name = f"{STORAGE_PATH}/{ts}-{tag}.tar.gz"
    _req(f"{url}/storage/v1/object/{BUCKET}/{name}", method="POST", key=key,
         data=payload, headers={"Content-Type": "application/gzip", "x-upsert": "true"})
    return name


def list_backups(url: str, key: str) -> list:
    r = _req(f"{url}/storage/v1/object/list/{BUCKET}", method="POST", key=key,
             data=json.dumps({"prefix": f"{STORAGE_PATH}/", "limit": 20, "offset": 0}).encode(),
             headers={"Content-Type": "application/json"})
    return sorted(o["name"] for o in json.loads(r.read()))


def main() -> int:
    p = argparse.ArgumentParser(prog="repo_backup")
    p.add_argument("--list", action="store_true")
    p.add_argument("--tag", default="manual")
    args = p.parse_args()

    url, key = _cfg()
    ensure_bucket(url, key)
    if args.list:
        for n in list_backups(url, key):
            print(" ", n)
        return 0
    payload = make_archive()
    name = push_backup(url, key, payload, args.tag)
    print(f"repo-backup: pushed {len(payload)/1024/1024:.1f} MB -> {BUCKET}/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
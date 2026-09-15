# -*- coding: utf-8 -*-
"""Verified YouTube/web search for Abdulrahman AI OS (read-only, stdlib-only).

Providers (in order):
  1. YouTube Data API v3 when YOUTUBE_API_KEY is set (reliable, titles+channels).
  2. DuckDuckGo HTML results filtered to verified YouTube URLs (no key needed).

Every returned URL is verified to be a real YouTube watch URL and normalized
to ``https://www.youtube.com/watch?v=<11-char-id>`` with tracking parameters
stripped. Anything else is rejected — the bot can therefore present these
links as-is instead of claiming it cannot browse.

Privacy: queries are sanitized (phones, e-mails, ID-like digit runs removed)
before any external call. Read-only: no approval gate needed, consistent with
the other read-only connectors. All failures are fail-soft (``ok: False``).

CLI:
  python3 -m connectors.web_search "ملخص العادات الذرية"
  python3 -m connectors.web_search "Atomic Habits" --json --max 3
  python3 -m connectors.web_search --check   # provider self-check (network)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

USER_AGENT = "AbdulrahmanAIOS/1.0 (verified-video-search; contact: local-bot)"
MAX_QUERY_CHARS = 200
MAX_RESULTS_LIMIT = 10
DEFAULT_TIMEOUT = 20
CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 50

_CACHE: dict = {}

# ---------------------------------------------------------------- queries

_VIDEO_WORDS = (
    r"يوتيوب|يوتوب|يو\s+تيوب|فيديو|فديو|مقطع|مقاطع|فيديوهات|"
    r"youtube|video|videos|clip|clips"
)
_ASK_WORDS = (
    r"رابط|روابط|ابحث|بحث|اعط|أعط|ارسل|أرسل|جيب|هات|شارك|زود|"
    r"link|links|search|find|send|give|show|share|watch"
)
_VIDEO_RE = re.compile(_VIDEO_WORDS, re.I)
_ASK_RE = re.compile(_ASK_WORDS, re.I)
_DIRECT_URL_RE = re.compile(r"youtube\.com|youtu\.be", re.I)
_NEGATION_RE = re.compile(r"(لا|بدون|من غير|not|don't|do not).{0,24}(رابط|ترسل|تعط|تبحث|send|link)", re.I)
_COMMAND_PREFIX_RE = re.compile(r"^\s*/(youtube|search)(@\w+)?\s*", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-.]{7,}\d")
_ID_RUN_RE = re.compile(r"\b\d{9,}\b")

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def sanitize_query(text: str, max_len: int = MAX_QUERY_CHARS) -> str:
    """Strip command prefixes and private identifiers from a search query."""
    query = _COMMAND_PREFIX_RE.sub("", str(text or ""))
    query = _EMAIL_RE.sub(" ", query)
    query = _PHONE_RE.sub(" ", query)
    query = _ID_RUN_RE.sub(" ", query)
    query = re.sub(r"\s+", " ", query).strip(" ،,.-")
    return query[:max_len].strip()


def is_video_link_request(text: str) -> bool:
    """True when the user asks for video/YouTube links (Arabic or English)."""
    value = str(text or "")
    if not value.strip():
        return False
    if _DIRECT_URL_RE.search(value):
        return True
    if _NEGATION_RE.search(value):
        return False
    return bool(_VIDEO_RE.search(value) and _ASK_RE.search(value))


def answer_has_video_links(answer: str) -> bool:
    return bool(_DIRECT_URL_RE.search(str(answer or "")))


# ---------------------------------------------------------------- URL verify

def extract_video_id(url: str) -> str | None:
    """Return the 11-char YouTube video id, or None for anything else."""
    try:
        parts = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return None
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if host in {"youtu.be"}:
        candidate = parts.path.strip("/").split("/")[0]
        return candidate if _VIDEO_ID_RE.match(candidate) else None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parts.path == "/watch":
            candidate = urllib.parse.parse_qs(parts.query).get("v", [""])[0]
            return candidate if _VIDEO_ID_RE.match(candidate) else None
        if parts.path.startswith("/shorts/") or parts.path.startswith("/embed/"):
            candidate = parts.path.split("/")[2] if len(parts.path.split("/")) > 2 else ""
            return candidate if _VIDEO_ID_RE.match(candidate) else None
    return None


def verify_youtube_url(url: str) -> str | None:
    """Normalize to a canonical watch URL, or None when not a real video URL."""
    video_id = extract_video_id(url)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------- providers

def _fetch(url: str, timeout: int, params: dict | None = None) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(raw or ""))
    return html.unescape(text).strip()


def _ddg_video_search(query: str, max_results: int, timeout: int) -> list:
    """Search DuckDuckGo HTML and keep only verified YouTube videos."""
    payload = _fetch(
        "https://html.duckduckgo.com/html/",
        timeout,
        {"q": f"{query} site:youtube.com"},
    ).decode("utf-8", "replace")
    anchors = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        payload, re.I | re.S,
    )
    results, seen = [], set()
    for href, inner in anchors:
        href = html.unescape(href)
        if "uddg=" in href:
            href = urllib.parse.unquote(
                urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])[0]
                or href.split("uddg=", 1)[1].split("&", 1)[0]
            )
        url = verify_youtube_url(href)
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({"title": _clean_title(inner)[:120] or "مقطع يوتيوب",
                        "url": url, "channel": ""})
        if len(results) >= max_results:
            break
    return results


def _youtube_api_search(query: str, max_results: int, timeout: int) -> list:
    """Search via YouTube Data API v3 (requires YOUTUBE_API_KEY)."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    payload = _fetch(
        "https://www.googleapis.com/youtube/v3/search",
        timeout,
        {"part": "snippet", "type": "video", "videoEmbeddable": "true",
         "safeSearch": "strict", "maxResults": max(1, min(max_results, 50)),
         "q": query, "key": key},
    ).decode("utf-8", "replace")
    data = json.loads(payload)
    if "error" in data:
        message = str(data["error"].get("message", "youtube api error"))
        raise RuntimeError(f"YouTube API: {message[:160]}")
    results, seen = [], set()
    for item in data.get("items", []):
        video_id = str((item.get("id") or {}).get("videoId", ""))
        url = verify_youtube_url(f"https://www.youtube.com/watch?v={video_id}")
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = item.get("snippet") or {}
        results.append({"title": str(snippet.get("title", "")).strip()[:120] or "مقطع يوتيوب",
                        "url": url,
                        "channel": str(snippet.get("channelTitle", "")).strip()[:80]})
        if len(results) >= max_results:
            break
    return results


def _cache_get(key):
    row = _CACHE.get(key)
    if not row:
        return None
    expires, results = row
    if expires < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return results


def _cache_put(key, results):
    if len(_CACHE) >= CACHE_MAX_ENTRIES:
        _CACHE.clear()
    _CACHE[key] = (time.monotonic() + CACHE_TTL_SECONDS, results)


def search_videos(query: str, max_results: int = 5, timeout: int = DEFAULT_TIMEOUT,
                  provider: str = "auto") -> dict:
    """Search YouTube videos. Fail-soft: always returns a dict, never raises."""
    clean = sanitize_query(query)
    if not clean:
        return {"ok": False, "results": [], "provider": "none", "error": "empty query"}
    want = max(1, min(int(max_results or 5), MAX_RESULTS_LIMIT))
    mode = (provider or "auto").strip().lower()
    if mode == "auto":
        mode = "youtube_api" if os.environ.get("YOUTUBE_API_KEY", "").strip() else "ddg"
    cache_key = (mode, clean, want)
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"ok": True, "results": cached, "provider": f"{mode}+cache", "error": ""}
    errors = []
    chain = [mode] + (["ddg"] if mode == "youtube_api" else [])
    for name in chain:
        try:
            if name == "youtube_api":
                results = _youtube_api_search(clean, want, timeout)
            else:
                results = _ddg_video_search(clean, want, timeout)
        except Exception as exc:  # noqa: fail-soft by design
            errors.append(f"{name}: {str(exc)[:140]}")
            continue
        if results:
            _cache_put(cache_key, results)
            return {"ok": True, "results": results, "provider": name, "error": ""}
        errors.append(f"{name}: no verified results")
    return {"ok": False, "results": [], "provider": mode, "error": "; ".join(errors)[:300]}


# ---------------------------------------------------------------- formatting

def format_links_section(results: list, query: str = "") -> str:
    """User-facing verified-links block (full URLs stay clickable on purpose)."""
    items = [r for r in (results or []) if r.get("url")]
    if not items:
        return ""
    head = f"🔗 روابط يوتيوب موثقة ({len(items)})"
    if query:
        head += f" — «{str(query).strip()[:60]}»"
    lines = ["", "", head + ":", ""]
    for pos, item in enumerate(items, 1):
        title = str(item.get("title", "")).strip()[:90] or "مقطع يوتيوب"
        channel = str(item.get("channel", "")).strip()[:60]
        lines.append(f"{pos}. {title}" + (f" — {channel}" if channel else ""))
        lines.append(str(item["url"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def verified_context_block(results: list, query: str = "") -> str:
    """Model-facing evidence block: present these links, invent nothing."""
    items = [r for r in (results or []) if r.get("url")]
    if not items:
        return ""
    lines = ["VERIFIED VIDEO LINKS (real search results, URLs already verified):"]
    if query:
        lines.append(f"query: {str(query).strip()[:120]}")
    for pos, item in enumerate(items, 1):
        lines.append(f"{pos}. {str(item.get('title', ''))[:100]} — {item['url']}")
    lines.append("Instruction: present these exact links in the user's language. "
                 "Never invent other video URLs and never claim inability to browse "
                 "when these verified links are provided.")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    max_results = 5
    if "--max" in args:
        try:
            max_results = int(args[args.index("--max") + 1])
        except (ValueError, IndexError):
            print("usage: --max N", file=sys.stderr)
            return 2
    if "--check" in args:
        key = bool(os.environ.get("YOUTUBE_API_KEY", "").strip())
        print(json.dumps({"provider": "youtube_api" if key else "ddg",
                          "api_key_set": key}, ensure_ascii=False))
        out = search_videos("تهيئة البحث", max_results=1, timeout=25)
        print(json.dumps({"ok": out["ok"], "provider": out["provider"],
                          "results": len(out["results"]),
                          "error": out["error"]}, ensure_ascii=False))
        return 0 if out["ok"] else 1
    query = " ".join(a for a in args if not a.startswith("--")).strip()
    if not query:
        print("usage: python3 -m connectors.web_search \"query\" [--json] [--max N] [--check]")
        return 2
    out = search_videos(query, max_results=max_results)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif out["results"]:
        print(format_links_section(out["results"], query))
    else:
        print(f"لا نتائج موثقة. ({out['error'][:160]})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

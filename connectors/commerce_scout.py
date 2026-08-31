# -*- coding: utf-8 -*-
"""Read-only Saudi retail deal scout.

Uses Brave Search only for discovery, then fetches retailer pages directly and
extracts a conservative price/pack match. Search snippets alone are never marked
verified. Checkout is handled elsewhere.
"""
from __future__ import annotations

import html, json, os, re, urllib.parse, urllib.request
from decimal import Decimal
from connectors.commerce_agent import Offer, make_offer, rank_offers

_ALLOWED = {
    "riyal1.com", "www.riyal1.com", "noon.com", "www.noon.com", "supermall.noon.com",
    "order.lamina-ksa.com", "azwasa.com", "www.azwasa.com", "tbmart.sa", "www.tbmart.sa",
    "cleandishes1.com", "www.cleandishes1.com",
}
_PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:ر\.?\s*س|SAR|ريال)", re.I)
_PACK10_RE = re.compile(r"(?:10|١٠)\s*(?:علب|عبوات|مغلفات|قطع|pack|boxes|pcs)", re.I)
_COUNT_RE = re.compile(r"(?:×|x|داخل\s+(?:الواحد\s+)?(?:المغلف|العلبة)|تضم)\s*(\d{2,4})\s*(?:منديل|ورقة)?", re.I)


def _brave(query: str, count: int = 10) -> list[dict]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured")
    qs = urllib.parse.urlencode({"q": query, "country": "SA", "search_lang": "ar", "count": max(1, min(count, 20))})
    req = urllib.request.Request(
        "https://api.search.brave.com/res/v1/web/search?" + qs,
        headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": "Abdulrahman-AI-OS/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return list(((data.get("web") or {}).get("results") or []))


def _plain(raw: str) -> str:
    raw = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _verify_page(url: str, required_pack: int = 10) -> Offer | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in _ALLOWED:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Abdulrahman-AI-OS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            text = _plain(r.read(1_500_000).decode("utf-8", errors="replace"))
    except Exception:
        return None
    if required_pack == 10 and not _PACK10_RE.search(text):
        return None
    price_match = _PRICE_RE.search(text)
    if not price_match:
        return None
    title = text[:240]
    m_title = re.search(r"(?:مناديل|tissues?)[^|]{0,180}", text, re.I)
    if m_title:
        title = m_title.group(0).strip()
    count = None
    m_count = _COUNT_RE.search(text)
    if m_count:
        try: count = int(m_count.group(1))
        except Exception: count = None
    retailer = parsed.hostname or "unknown"
    return make_offer(
        retailer=retailer,
        title=title,
        pack_count=required_pack,
        item_count_each=count,
        price_sar=price_match.group(1).replace(",", "."),
        shipping_sar=None,
        url=url,
        in_stock=not bool(re.search(r"غير\s+متوفر|out\s+of\s+stock", text, re.I)),
        price_verified=True,
        shipping_verified=False,
    )


def scout(query: str, required_pack: int = 10, max_results: int = 8) -> list[Offer]:
    search_q = f"{query} {required_pack} علب السعودية سعر"
    results = _brave(search_q, count=max_results * 2)
    offers = []
    seen = set()
    for item in results:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        offer = _verify_page(url, required_pack=required_pack)
        if offer:
            offers.append(offer)
        if len(offers) >= max_results:
            break
    return rank_offers(offers, required_pack)


def render_offers(offers: list[Offer]) -> str:
    if not offers:
        return "لم أجد عروضًا موثقة مطابقة الآن."
    lines = ["🛒 عروض موثقة — السعر النهائي يحتاج شحنًا مؤكدًا قبل الاختيار النهائي"]
    for i, o in enumerate(offers, 1):
        shipping = f"{o.shipping_sar} ر.س" if o.shipping_sar is not None else "NEEDS_INPUT"
        total = f"{o.total_sar} ر.س" if o.total_sar is not None else "NEEDS_INPUT"
        lines.append(f"{i}. {o.retailer} — {o.title[:90]} — المنتج {o.price_sar} ر.س — الشحن {shipping} — الإجمالي {total}")
    return "\n".join(lines)

# -*- coding: utf-8 -*-
"""Fail-closed customer checkout executor for supported Zid storefronts.

This module is intentionally narrow:
- it accepts only an already-approved order plan;
- it never accepts raw card data;
- supported payment modes are PAYMENT_LINK or COD;
- it refuses totals above the approved ceiling;
- it returns an order_id only after the storefront exposes order evidence.

The first supported target is a Zid storefront such as riyal1.com. Selectors are
text/label based and every uncertain step fails closed rather than guessing.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _allowed_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().strip(".")
    allowed = [x.strip().lower().strip(".") for x in os.environ.get("COMMERCE_BROWSER_ALLOWED_DOMAINS", "").split(",") if x.strip()]
    return bool(host and allowed and any(host == a or host.endswith("." + a) for a in allowed))


@dataclass
class CheckoutResult:
    order_id: str
    status: str
    total_sar: str
    payment_url: str = ""

    def as_dict(self) -> dict:
        out = {"order_id": self.order_id, "status": self.status, "total_sar": self.total_sar}
        if self.payment_url:
            out["payment_url"] = self.payment_url
        return out


def _find_clickable(driver, labels: tuple[str, ...]):
    from selenium.webdriver.common.by import By
    candidates = driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']")
    for el in candidates:
        try:
            text = " ".join((el.text or "").split()).lower()
            if text and any(label.lower() in text for label in labels) and el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def _fill_by_hints(driver, hints: tuple[str, ...], value: str) -> bool:
    from selenium.webdriver.common.by import By
    fields = driver.find_elements(By.CSS_SELECTOR, "input, textarea")
    for el in fields:
        try:
            blob = " ".join([
                el.get_attribute("name") or "",
                el.get_attribute("id") or "",
                el.get_attribute("placeholder") or "",
                el.get_attribute("aria-label") or "",
            ]).lower()
            if any(h.lower() in blob for h in hints) and el.is_displayed() and el.is_enabled():
                el.clear()
                el.send_keys(value)
                return True
        except Exception:
            continue
    return False


def _page_total(driver) -> Decimal | None:
    text = (driver.page_source or "").replace("٬", ",")
    # Prefer totals near SAR/ر.س; take the largest plausible amount on checkout page.
    vals = []
    for raw in re.findall(r"(\d+(?:[\.,]\d{1,2})?)\s*(?:ر\.س|ريال|SAR)", text, flags=re.I):
        try:
            vals.append(_d(raw.replace(",", "")))
        except Exception:
            pass
    return max(vals) if vals else None


def _extract_order_evidence(driver) -> tuple[str, str]:
    url = driver.current_url or ""
    for pat in (r"/o/([A-Za-z0-9_-]{5,})", r"order(?:_id|[-/])([A-Za-z0-9_-]{5,})"):
        m = re.search(pat, url, flags=re.I)
        if m:
            return m.group(1), url
    body = driver.page_source or ""
    for pat in (r"(?:رقم\s*الطلب|order\s*(?:number|id))\s*[:#-]?\s*([A-Za-z0-9_-]{5,})",):
        m = re.search(pat, body, flags=re.I)
        if m:
            return m.group(1), url
    return "", url


def execute(plan: dict, delivery: dict, payment_profile: str, driver=None) -> dict:
    """Execute one approved checkout. Raises on any ambiguity.

    `driver` is injectable for tests. When omitted a headless Chromium Selenium
    driver is created. No raw card information is accepted or processed.
    """
    product_url = str(plan.get("url") or "").strip()
    if not _allowed_host(product_url):
        raise RuntimeError("UNSUPPORTED_RETAILER_DOMAIN")
    max_total = _d(plan.get("max_total_sar") or plan.get("delivered_total_sar"))
    mode = (payment_profile or "").strip().upper()
    if mode not in {"PAYMENT_LINK", "COD"}:
        raise RuntimeError("PAYMENT_PROFILE_UNSUPPORTED: use PAYMENT_LINK or COD")
    address = str(delivery.get("address") or "").strip()
    phone = str(delivery.get("phone") or "").strip()
    if not address or not phone:
        raise RuntimeError("DELIVERY_PROFILE_INCOMPLETE")

    owns_driver = driver is None
    if owns_driver:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,1200")
        binary = os.environ.get("CHROME_BIN", "").strip()
        if binary:
            options.binary_location = binary
        driver = webdriver.Chrome(options=options)

    try:
        driver.set_page_load_timeout(45)
        driver.get(product_url)
        time.sleep(1.5)

        add = _find_clickable(driver, ("أضف للسلة", "اضف للسلة", "add to cart"))
        if not add:
            raise RuntimeError("ADD_TO_CART_NOT_FOUND")
        add.click()
        time.sleep(1.2)

        checkout = _find_clickable(driver, ("إتمام الطلب", "اتمام الطلب", "إكمال الطلب", "اكمال الطلب", "checkout"))
        if not checkout:
            # Zid storefronts normally expose /cart.
            p = urlparse(product_url)
            driver.get(f"{p.scheme}://{p.netloc}/cart")
            time.sleep(1.0)
            checkout = _find_clickable(driver, ("إتمام الطلب", "اتمام الطلب", "إكمال الطلب", "اكمال الطلب", "checkout"))
        if not checkout:
            raise RuntimeError("CHECKOUT_ENTRY_NOT_FOUND")
        checkout.click()
        time.sleep(1.5)

        if not _fill_by_hints(driver, ("phone", "mobile", "جوال", "الهاتف"), phone):
            raise RuntimeError("PHONE_FIELD_NOT_FOUND")
        if not _fill_by_hints(driver, ("address", "street", "العنوان", "الشارع"), address):
            raise RuntimeError("ADDRESS_FIELD_NOT_FOUND")

        observed_total = _page_total(driver)
        if observed_total is None:
            raise RuntimeError("CHECKOUT_TOTAL_NOT_VERIFIED")
        if observed_total > max_total:
            raise RuntimeError("PRICE_CEILING_VIOLATION")

        if mode == "PAYMENT_LINK":
            pay = _find_clickable(driver, ("إرسال رابط دفع", "ارسال رابط دفع", "payment link"))
            if not pay:
                raise RuntimeError("PAYMENT_LINK_METHOD_NOT_FOUND")
            pay.click()
        else:
            cod = _find_clickable(driver, ("الدفع عند الاستلام", "cash on delivery", "cod"))
            if not cod:
                raise RuntimeError("COD_METHOD_NOT_FOUND")
            cod.click()
        time.sleep(0.5)

        submit = _find_clickable(driver, ("تأكيد الطلب", "تاكيد الطلب", "إتمام الطلب", "اتمام الطلب", "place order", "confirm order"))
        if not submit:
            raise RuntimeError("FINAL_SUBMIT_NOT_FOUND")
        submit.click()
        time.sleep(2.0)

        order_id, result_url = _extract_order_evidence(driver)
        if not order_id:
            raise RuntimeError("ORDER_ID_NOT_CONFIRMED")
        status = "payment_required" if mode == "PAYMENT_LINK" else "submitted"
        payment_url = result_url if mode == "PAYMENT_LINK" else ""
        return CheckoutResult(order_id=order_id, status=status, total_sar=str(observed_total), payment_url=payment_url).as_dict()
    finally:
        if owns_driver and driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

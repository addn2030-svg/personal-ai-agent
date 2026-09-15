# -*- coding: utf-8 -*-
"""بوابة الدفع التفويضي — سياسة عتبة 375 ريال + التنفيذ المحروس.

السياسة (مطابقة لسقف التجارة التجريبية في connectors/commerce_agent.py):

  المبلغ  < 375 ريال (~100$ عند ربط 3.75)  ← تفويض مسبق: money L1 → **L3**
                                               تنفيذ فعلي عبر موصل الدفع + إيصال + تراجع
  المبلغ ≥ 375 ريال                          ← **RED**: لا تنفيذ إطلاقًا؛ تنبيه فوري
                                               + مسودة في طابور الاعتماد (PENDING_APPROVAL)

حدود على مستوى الكود (ليست متغيرات بيئة) حتى لا يرفع خطأ مطبعي في المنصة
سقف التعرّض المالي المسموح — متغيرات البيئة تخفض السقف فقط، ولا ترفعه أبدًا:

  MONEY_AUTOPAY_MAX_SAR        سقف العملية الواحدة  (افتراضي/أقصى 375.00)
  MONEY_AUTOPAY_DAILY_MAX_SAR  سقف اليوم التراكمي (افتراضي/أقصى 375.00)

ولا يُنفَّذ شيء ما لم تتحقق **كل** الحواجز التالية معًا:

  1. MONEY_AUTOPAY_ENABLED=1                       (الافتراضي 0 ← تجهيز/تنبيه كالسابق)
  2. MONEY_AUTOPAY_ACK=I_AUTHORIZE_SUB_375_SAR_AUTOPAY   (إقرار صريح من المالك)
  3. PAYMENT_GATEWAY_WEBHOOK_URL + PAYMENT_GATEWAY_SHARED_SECRET (موصل دفع حقيقي)
  4. المبلغ معلوم وموجب وأقل من العتبة — المجهول لا يُخمَّن ولا يُدفع
  5. السقف اليومي التراكمي غير مستهلك
  6. مفتاح عدم التكرار (idempotency) لم يُنفَّذ سابقًا — لا دفع مزدوج أبدًا

أي حاجز ناقص ← `evaluate()` يعيد التفويض=False مع السبب، ويعود المحرك فورًا إلى
السلوك المحافظ: مسودة PENDING_APPROVAL بانتظار نقرة المالك.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation

# --- حدود الكود الصارمة: ربط 3.75 ريال/دولار × 100$ -------------------------
HARD_MAX_SAR = Decimal("375.00")
USD_PEG_SAR = Decimal("3.75")
ACK_PHRASE = "I_AUTHORIZE_SUB_375_SAR_AUTOPAY"
LEDGER_SECTION = "autopay_executions"

# أنواع المحفزات المالية المشمولة بالتفويض (لا شيء غيرها)
MONEY_KINDS = ("bill_due", "renewal_watch", "missed_recovery")


def _d(value) -> Decimal | None:
    """تحويل آمن إلى Decimal بمنازل قرشين — None عند الجهل/التلف (لا تخمين)."""
    if value in (None, "", "NEEDS_INPUT"):
        return None
    if isinstance(value, Decimal):
        out = value
    else:
        try:
            out = Decimal(str(value).replace(",", ".").strip())
        except (InvalidOperation, ValueError, TypeError):
            return None
    if not out.is_finite():
        return None
    return out.quantize(Decimal("0.01"))


def amount_of(value) -> Decimal | None:
    """واجهة عامة للتحويل الآمن إلى Decimal (منازل قرشين) — None عند الجهل."""
    return _d(value)


def money_of(row) -> Decimal | None:
    """مبلغ البند المالي: أول حقل صريح موجود (لا تخمين ولا افتراض)."""
    if not isinstance(row, dict):
        return None
    for key in ("amount_sar", "المبلغ المستحق (ريال)", "المبلغ (ريال)",
                "المبلغ", "amount", "التكلفة (ريال/شهر)", "cost"):
        value = _d(row.get(key))
        if value is not None:
            return value
    return None


def _env_decimal(name: str, default: Decimal, ceiling: Decimal) -> Decimal:
    """متغير بيئة يخفض السقف فقط — أي قيمة أعلى من سقف الكود تُقتطع إليه."""
    value = _d(os.environ.get(name, ""))
    if value is None or value <= 0:
        value = default
    return min(value, ceiling)


def threshold_sar() -> Decimal:
    """عتبة التفويض الفعلية للعملية الواحدة (≤ 375.00 دائمًا)."""
    return _env_decimal("MONEY_AUTOPAY_MAX_SAR", HARD_MAX_SAR, HARD_MAX_SAR)


def daily_cap_sar() -> Decimal:
    """السقف التراكمي لليوم الواحد بتوقيت الرياض (≤ 375.00 دائمًا)."""
    return _env_decimal("MONEY_AUTOPAY_DAILY_MAX_SAR", HARD_MAX_SAR, HARD_MAX_SAR)


def usd(amount) -> Decimal:
    """تقريب استرشادي بالدولار عند الربط الثابت 3.75 ريال/دولار."""
    value = _d(amount) or Decimal("0.00")
    return (value / USD_PEG_SAR).quantize(Decimal("1"))


def threshold_text() -> str:
    t = threshold_sar()
    return f"{t.normalize()} SAR (~{usd(t)}$)"


def acked() -> bool:
    return os.environ.get("MONEY_AUTOPAY_ACK", "").strip() == ACK_PHRASE


def autopay_flag() -> bool:
    return os.environ.get("MONEY_AUTOPAY_ENABLED", "0").strip() == "1"


def gateway_ready() -> bool:
    return bool(os.environ.get("PAYMENT_GATEWAY_WEBHOOK_URL", "").strip()
                and os.environ.get("PAYMENT_GATEWAY_SHARED_SECRET", "").strip())


def ready() -> bool:
    """هل مسار التنفيذ الفعلي مسلّح بالكامل؟ (بدونه يبقى كل شيء مسودة)"""
    return autopay_flag() and acked() and gateway_ready()


def readiness() -> dict:
    return {
        "threshold_sar": str(threshold_sar()),
        "daily_cap_sar": str(daily_cap_sar()),
        "autopay_enabled": autopay_flag(),
        "owner_ack": acked(),
        "gateway_configured": gateway_ready(),
        "execution_armed": ready(),
        "level_below_threshold": "L3",
        "level_at_or_above_threshold": "L1",
    }


# ---------------------------------------------------------------- دفتر التنفيذ
def ledger(S) -> list[dict]:
    if not isinstance(S, dict):
        return []
    rows = S.get(LEDGER_SECTION)
    return rows if isinstance(rows, list) else []


def day_of(value) -> str:
    """يوم الرياض من طابع زمني (ISO) — لتجميع السقف اليومي."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace(" ", "T"))
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz).date().isoformat()


EXECUTED_STATUSES = ("EXECUTED", "REVERSED")
# التعرّض الملتزم به: ما نُفّذ + ما فُوِّض في الدورة نفسها (لم يُسدَّد بعد).
# يُحسب ضد السقف اليومي حتى لا يُفوَّض 400 ريال من نيّتين قبل تنفيذ الأولى.
EXPOSURE_STATUSES = ("AUTHORIZED", "EXECUTED")


def spent_today(S, today: str) -> Decimal:
    """التعرّض المالي الملتزم به اليوم (AUTHORIZED+EXECUTED) — للسقف اليومي.

    لا يُحسب المرفوض/الملغى/الفاشل/المستردّ (REVERSED أعاد المال).
    """
    total = Decimal("0.00")
    for row in ledger(S):
        if str(row.get("status")) not in EXPOSURE_STATUSES:
            continue
        if str(row.get("day"))[:10] != str(today)[:10]:
            continue
        total += _d(row.get("amount_sar")) or Decimal("0.00")
    return total


def settled_today(S, today: str) -> Decimal:
    """ما استقر فعلًا اليوم (EXECUTED فقط) — لفحص السقف لحظة التنفيذ.

    يستثني AUTHORIZED (نيّة لم تُسدَّد بعد) حتى لا يعدّ الصف الجاري تنفيذَه
    ضد نفسه عند إعادة فحص السقف داخل المنفّذ.
    """
    total = Decimal("0.00")
    for row in ledger(S):
        if str(row.get("status")) != "EXECUTED":
            continue
        if str(row.get("day"))[:10] != str(today)[:10]:
            continue
        total += _d(row.get("amount_sar")) or Decimal("0.00")
    return total


def find_by_key(S, idempotency_key: str) -> dict | None:
    for row in ledger(S):
        if str(row.get("idempotency_key")) == str(idempotency_key):
            return row
    return None


# ---------------------------------------------------------------- قرار التفويض
def evaluate(amount, *, S=None, today="", idempotency_key="") -> dict:
    """الحكم الحتمي: هل هذا المبلغ مفوَّض للتنفيذ الفعلي الآن؟

    يعيد {"authorized": bool, "reason": str, "level": "L3"|"L1", ...} — والسبب
    دائمًا قابل للتدقيق، لأن كل رفض يعني عودة الإجراء إلى طابور الاعتماد.
    """
    state = S if isinstance(S, dict) else {}
    amount_d = _d(amount)
    threshold = threshold_sar()
    daily_cap = daily_cap_sar()
    out = {
        "amount_sar": str(amount_d) if amount_d is not None else None,
        "amount_usd": str(usd(amount_d)) if amount_d is not None else None,
        "threshold_sar": str(threshold),
        "daily_cap_sar": str(daily_cap),
        "daily_spent_sar": str(spent_today(state, today) if today else "0.00"),
        "authorized": False,
        "level": "L1",
        "reason": "",
        "guard": "",
    }

    if amount_d is None:
        out.update(reason="المبلغ غير معلوم — لا يُدفع مجهول أبدًا", guard="amount_unknown")
        return out
    if amount_d >= threshold:
        out.update(reason=f"{amount_d.normalize()} ≥ عتبة {threshold.normalize()} ريال — "
                          "تنبيه أحمر + مسودة للاعتماد، لا تنفيذ",
                   guard="at_or_above_threshold", level="L1")
        return out
    out["level"] = "L3"
    if not autopay_flag():
        out.update(reason="MONEY_AUTOPAY_ENABLED≠1 — التفويض مطفأ (مسودة للاعتماد)",
                   guard="disabled_env")
        return out
    if not acked():
        out.update(reason=f"ينقص الإقرار الصريح MONEY_AUTOPAY_ACK={ACK_PHRASE}",
                   guard="missing_ack")
        return out
    if not gateway_ready():
        out.update(reason="موصل الدفع غير مضبوط (PAYMENT_GATEWAY_WEBHOOK_URL/SECRET)",
                   guard="gateway_missing")
        return out
    if amount_d <= 0:
        out.update(reason="المبلغ غير موجب", guard="amount_nonpositive")
        return out
    if idempotency_key:
        prior = find_by_key(state, idempotency_key)
        if prior and str(prior.get("status")) in EXECUTED_STATUSES:
            out.update(reason="نُفّذ سابقًا بالمفتاح نفسه — لا دفع مزدوج",
                       guard="duplicate", prior_id=prior.get("payment_id"))
            return out
    if today:
        spent = spent_today(state, today)
        out["daily_spent_sar"] = str(spent)
        if spent + amount_d > daily_cap:
            out.update(reason=f"السقف اليومي {daily_cap.normalize()} ريال: "
                              f"صُرف {spent.normalize()} + {amount_d.normalize()} يتجاوزه",
                       guard="daily_cap")
            return out
    out.update(authorized=True,
               reason=f"دفع تلقائي <{threshold.normalize()} ريال — L3 مصرّح")
    return out


# ---------------------------------------------------------------- التنفيذ والتراجع
def _post(payload: dict, timeout: int = 45) -> dict:
    url = os.environ.get("PAYMENT_GATEWAY_WEBHOOK_URL", "").strip()
    secret = os.environ.get("PAYMENT_GATEWAY_SHARED_SECRET", "").strip()
    if not url or not secret:
        raise RuntimeError("PAYMENT_GATEWAY_UNCONFIGURED")
    body = dict(payload)
    body["secret"] = secret
    # رؤوس HTTP لاتينية-1 فقط: المفتاح الحتمي قد يحوي عربية، فنرسل في الرأس بصمةً
    # ASCII آمنة (sha256) — المفتاح الكامل يبقى في جسم JSON (UTF-8) للتدقيق وعدم التكرار.
    raw_key = str(body.get("idempotency_key", ""))
    header_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest() if raw_key else ""
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "X-Payment-Idempotency-Key": header_key},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("PAYMENT_GATEWAY_BAD_RESPONSE")
    return data


def execute(*, amount, payee, idempotency_key, reference="", purpose="",
            source="", due=None, timeout=45) -> dict:
    """تنفيذ فعلي واحد — يعيد إيصالًا {"payment_id","status","amount_sar",...}.

    يفشل صراحةً (RuntimeError) عند أي انتهاك؛ لا يخصم شيئًا بصمت ولا يعيد
    «نجاحًا» بلا معرّف دفع حقيقي من المزوّد.
    """
    amount_d = _d(amount)
    if amount_d is None or amount_d <= 0:
        raise ValueError(f"AMOUNT_INVALID: {amount!r}")
    if amount_d > HARD_MAX_SAR:
        raise RuntimeError(f"AUTOPAY_LIMIT_EXCEEDED: سقف الكود {HARD_MAX_SAR} ريال")
    if amount_d >= threshold_sar():
        raise RuntimeError(f"THRESHOLD_EXCEEDED: {amount_d} ≥ {threshold_sar()} ريال")
    if not str(idempotency_key).strip():
        raise RuntimeError("IDEMPOTENCY_KEY_REQUIRED")
    result = _post({
        "action": "pay",
        "idempotency_key": str(idempotency_key),
        "amount_sar": str(amount_d),
        "max_amount_sar": str(threshold_sar()),
        "currency": "SAR",
        "payee": str(payee or "")[:160],
        "reference": str(reference or "")[:160],
        "purpose": str(purpose or "")[:240],
        "source": str(source or "")[:80],
        "due": str(due or "")[:10],
    }, timeout=timeout)
    if not result.get("ok"):
        raise RuntimeError("GATEWAY_REJECTED: " + str(result.get("error", "unknown"))[:200])
    payment_id = str(result.get("payment_id") or result.get("id") or "").strip()
    if not payment_id:
        raise RuntimeError("GATEWAY_NO_PAYMENT_ID")
    charged = _d(result.get("amount_sar", amount_d)) or amount_d
    if charged > amount_d:
        raise RuntimeError(f"AMOUNT_CEILING_VIOLATION: المزوّد خصم {charged} > {amount_d}")
    receipt = {
        "payment_id": payment_id,
        "status": str(result.get("status") or "executed"),
        "amount_sar": str(charged),
        "idempotency_key": str(idempotency_key),
        "gateway": os.environ.get("PAYMENT_GATEWAY_NAME", "").strip() or "webhook",
    }
    for key in ("provider", "reference_url", "refundable"):
        if result.get(key) is not None:
            receipt[key] = result[key]
    return receipt


def refund(payment_id: str, *, amount=None, idempotency_key="", reason="",
           timeout=45) -> dict:
    """مسار التراجع (undo): استرداد/إلغاء العملية المنفَّذة عبر المزوّد نفسه."""
    if not str(payment_id).strip():
        raise ValueError("PAYMENT_ID_REQUIRED")
    result = _post({
        "action": "refund",
        "payment_id": str(payment_id),
        "amount_sar": str(_d(amount)) if amount is not None else None,
        "idempotency_key": str(idempotency_key or f"undo:{payment_id}"),
        "reason": str(reason or "owner_undo")[:200],
    }, timeout=timeout)
    if not result.get("ok"):
        raise RuntimeError("REFUND_REJECTED: " + str(result.get("error", "unknown"))[:200])
    return {"refund_id": str(result.get("refund_id") or result.get("id") or ""),
            "status": str(result.get("status") or "refunded"),
            "amount_sar": str(_d(result.get("amount_sar", amount)) or _d(amount) or "")}


if __name__ == "__main__":
    print(json.dumps(readiness(), ensure_ascii=False, indent=2))

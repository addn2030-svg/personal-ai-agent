# -*- coding: utf-8 -*-
"""Telegram surface for Commerce Agent v0.4."""
from __future__ import annotations

import json
import os

from connectors import commerce_agent, commerce_scout, commerce_sandbox

_INSTALLED = False
_LAST_OFFERS: dict[int, list] = {}


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    from connectors import telegram_bot_legacy as legacy
    original_handle = legacy.handle_message
    original_start = legacy.command_start
    original_configure = legacy.configure_commands

    def command_start(chat_id: int):
        original_start(chat_id)
        legacy.send(
            chat_id,
            "\n🛒 Commerce Agent\n"
            "/commerce_test — اختبار كامل آمن بدون شراء حقيقي\n"
            "/shop المنتج — اقتنص عروضًا موثقة\n"
            "/prepare_order N — جهّز الطلب من العرض رقم N\n"
            "/approve_order ID CODE — وافق ونفّذ عبر Checkout connector\n"
            "/commerce_status — حالة البحث/التوصيل/الدفع/Checkout\n"
            "أو اكتب طبيعيًا: اطلب مناديل 10 علب بأفضل سعر.\n"
            "بيانات العنوان/الجوال لا تُرسل لمحرك البحث ولا تُحفظ في StateStore أو Sheets بواسطة Commerce Agent.",
        )

    def configure_commands():
        original_configure()
        try:
            commands = legacy.api("getMyCommands") or []
            existing = {str(x.get("command", "")) for x in commands}
            additions = [
                {"command": "commerce_test", "description": "اختبار Commerce آمن بدون شراء"},
                {"command": "shop", "description": "ابحث عن أفضل عروض موثقة"},
                {"command": "prepare_order", "description": "جهز طلبًا من عرض مختار"},
                {"command": "approve_order", "description": "اعتمد الشراء عبر Checkout connector"},
                {"command": "commerce_status", "description": "حالة Commerce Agent"},
            ]
            commands.extend(x for x in additions if x["command"] not in existing)
            legacy.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:
            print(f"Commerce command menu warning: {exc}", flush=True)

    def _status():
        profile = commerce_agent.delivery_profile_status()
        return (
            "🛒 Commerce Agent status\n"
            f"Brave deal scout: {'configured ✅' if os.environ.get('BRAVE_SEARCH_API_KEY','').strip() else 'not configured'}\n"
            f"Delivery profile: {'ready ✅' if profile['address_configured'] and profile['phone_configured'] else 'not ready'}\n"
            f"Payment profile: {'ready ✅' if profile['payment_profile_configured'] else 'not ready'}\n"
            f"Checkout connector: {'ready ✅' if commerce_agent.checkout_configured() else 'not connected'}\n"
            "Sandbox test: available ✅\n"
            "Purchase rule: preview → explicit approval → checkout receipt."
        )

    def _render_order_result(result: dict) -> str:
        receipt = (result.get("receipts") or [{}])[0]
        status = str(receipt.get("status") or "EXECUTED")
        if status == "payment_required":
            lines = [
                "✅ تم إنشاء الطلب لدى المتجر",
                f"رقم الطلب: {receipt.get('order_id')}",
                f"المتجر: {receipt.get('retailer')}",
                f"الإجمالي: {receipt.get('total_sar')} ر.س",
                "⚠️ الدفع لم يكتمل بعد.",
            ]
            payment_url = str(receipt.get("payment_url") or "").strip()
            if payment_url.startswith("https://"):
                lines.append("رابط الدفع الآمن: " + payment_url)
            return "\n".join(lines)
        return (
            "✅ تم تنفيذ الطلب\n"
            f"رقم الطلب: {receipt.get('order_id')}\n"
            f"المتجر: {receipt.get('retailer')}\n"
            f"الإجمالي: {receipt.get('total_sar')} ر.س"
        )

    def handle_message(message: dict):
        raw = (message.get("text") or message.get("caption") or "").strip()
        low = raw.lower()
        command = raw.split()[0].split("@")[0].lower() if raw else ""
        natural_shop = low.startswith(("اقتنص عروض ", "ابحث عن أفضل سعر ", "shop "))
        natural_order = any(x in low for x in ("اطلب ", "أطلب ", "اشتري ", "اشترِ ")) and any(x in low for x in ("أفضل سعر", "افضل سعر", "اقتنص", "العروض"))
        supported = command in {"/commerce_test", "/shop", "/prepare_order", "/approve_order", "/commerce_status"}
        if not supported and not natural_shop and not natural_order:
            return original_handle(message)
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        if not legacy._authorized(chat_id, chat.get("type", "")):
            legacy.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
            return
        text, kind, attachment = legacy._message_payload(message)
        safe_text = commerce_agent.redact_private(text)
        iid = legacy._local_capture(safe_text, message, kind)
        try:
            if command == "/commerce_test":
                answer = commerce_sandbox.render_smoke_test(commerce_sandbox.run_smoke_test())
            elif command == "/commerce_status":
                answer = _status()
            elif command == "/prepare_order":
                parts = raw.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    raise ValueError("الاستخدام: /prepare_order N")
                offers = _LAST_OFFERS.get(int(chat_id), [])
                idx = int(parts[1]) - 1
                if idx < 0 or idx >= len(offers):
                    raise ValueError("رقم العرض غير موجود؛ نفذ /shop أولًا.")
                preview = commerce_agent.create_order_preview(offers[idx], source_ref=f"telegram:{iid}")
                answer = commerce_agent.render_preview(preview)
            elif command == "/approve_order":
                parts = raw.split()
                if len(parts) != 3:
                    raise ValueError("الاستخدام: /approve_order ORDER_ID CODE")
                result = commerce_agent.execute_order(parts[1], parts[2])
                answer = _render_order_result(result)
            else:
                if natural_order:
                    query = commerce_agent.natural_order_product_query(raw)
                elif command == "/shop":
                    query = raw[len(command):].strip()
                elif low.startswith("اقتنص عروض "):
                    query = raw[len("اقتنص عروض "):].strip()
                elif low.startswith("ابحث عن أفضل سعر "):
                    query = raw[len("ابحث عن أفضل سعر "):].strip()
                else:
                    query = raw[5:].strip()
                if not query:
                    raise ValueError("NEEDS_INPUT: اكتب المنتج المطلوب.")
                offers = commerce_scout.scout(query, required_pack=10)
                _LAST_OFFERS[int(chat_id)] = offers
                answer = commerce_scout.render_offers(offers)
                if natural_order and offers and offers[0].total_sar is not None:
                    preview = commerce_agent.create_order_preview(offers[0], source_ref=f"telegram:{iid}")
                    answer += "\n\n" + commerce_agent.render_preview(preview)
                elif offers and offers[0].total_sar is not None:
                    answer += "\n\nالأفضل بالسعر النهائي المؤكد حاليًا: العرض 1.\nللتجهيز: /prepare_order 1"
            legacy.send(chat_id, answer)
            legacy._save_intake(iid, message, safe_text, kind, attachment, "COMPLETED")
        except Exception as exc:
            legacy.send(chat_id, "❌ " + str(exc)[:1200])
            legacy._save_intake(iid, message, safe_text, kind, attachment, "ERROR", error=exc)

    legacy.handle_message = handle_message
    legacy.command_start = command_start
    legacy.configure_commands = configure_commands
    _INSTALLED = True

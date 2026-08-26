# -*- coding: utf-8 -*-
"""Production webhook runtime patches.

P0/P1 rules implemented here without forking telegram_bot.py:
- /brief reads operational truth from StateStore and manual evidence from Sheets;
- /b is an alias of /brief;
- APPOINTMENT is classified as NEEDS_CONFIRMATION data, not a Calendar write;
- Sheets append retries carry a stable idempotency key.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request


def _install_idempotent_append(bot):
    if getattr(bot, "_AI_OS_IDEMPOTENT_APPEND", False):
        return
    raw_append = bot._append

    def append(tab: str, row: list):
        if bot.GOOGLE_SHEETS_WEBHOOK_URL and bot.GOOGLE_SHEETS_WEBHOOK_SECRET:
            fingerprint = hashlib.sha256(
                json.dumps([tab, row], ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            payload = json.dumps(
                {
                    "secret": bot.GOOGLE_SHEETS_WEBHOOK_SECRET,
                    "action": "append",
                    "tab": tab,
                    "row": row,
                    "idempotency_key": fingerprint,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                bot.GOOGLE_SHEETS_WEBHOOK_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            result = json.loads(urllib.request.urlopen(request, timeout=30).read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError("Sheets webhook: " + str(result.get("error", "unknown error")))
            return result
        return raw_append(tab, row)

    bot._append = append
    bot._AI_OS_IDEMPOTENT_APPEND = True


def _install_appointment_classification(bot):
    if getattr(bot, "_AI_OS_APPOINTMENT_CLASSIFIER", False):
        return
    original = bot._category
    appointment_re = re.compile(
        r"\bappointment\b|\bmeeting\b|\bbooking\b|موعد|اجتماع|حجز|زيارة|مراجعة\s+(?:طبية|عيادة)",
        re.I,
    )

    def category(text: str, kind: str = "TEXT"):
        value = text or ""
        if not bot._clinical_hint(value) and appointment_re.search(value):
            return "APPOINTMENT"
        return original(value, kind)

    bot._category = category
    bot._AI_OS_APPOINTMENT_CLASSIFIER = True


def _install_brief_alias(bot):
    if getattr(bot, "_AI_OS_BRIEF_ALIAS", False):
        return
    original = bot.handle_message
    alias_re = re.compile(r"^/b(?:@\w+)?(?=\s|$)", re.I)

    def handle_message(message: dict):
        text = message.get("text") or ""
        match = alias_re.match(text)
        if match:
            message = dict(message)
            message["text"] = "/brief" + text[match.end():]
        return original(message)

    bot.handle_message = handle_message
    bot._AI_OS_BRIEF_ALIAS = True


def install(bot):
    """Install production-only safety patches and the resilient /brief implementation."""
    _install_idempotent_append(bot)
    _install_appointment_classification(bot)
    _install_brief_alias(bot)

    def command_brief(chat_id: int):
        bot.send(chat_id, "🧠 أبني الـBrief من StateStore وأراجع المدخلات اليدوية في Sheets...")
        try:
            from connectors.brief_discovery import (
                compact_discovery,
                discover,
                normalize_snapshot,
                save_snapshot,
            )
            from connectors.sheet_intelligence import compact_context, snapshot, upsert_metrics
            from store import Store

            # Operational records are authoritative here. Sheets remains a bounded
            # human-input/projection surface until bidirectional reconciliation is complete.
            state = Store().rows_all()
            operational = {
                key: state.get(key, [])
                for key in (
                    "tasks", "projects", "waiting_for", "decision_requests",
                    "action_queue", "decisions", "meetings", "manager_markers"
                )
            }
            operational_context = json.dumps(
                operational, ensure_ascii=False, default=str, separators=(",", ":")
            )[:9000]

            live = snapshot(max_rows=80, max_cols=16)
            discovery = discover(live, persist=False)
            prompt = (
                "أنشئ Executive Brief عربيًا مختصرًا بصفتك مدير أعمال عبدالرحمن. "
                "قاعدة المصدر: OPERATIONAL STATE هو المرجع للحالة التشغيلية التي تنشئها الآلة، "
                "وMANUAL SHEETS EVIDENCE دليل للصفوف التي يحررها الإنسان يدويًا. عند التعارض "
                "لا تدمج القيم بصمت؛ اذكر التعارض واطلب reconciliation. استخدم فقط الأدلة المرفقة "
                "وافصل المؤكد عن الاستنتاج. رتّب النتيجة إلى: 1) أهم 3 أولويات 2) التغييرات "
                "3) المهام الناقصة 4) المواعيد القادمة 5) المخاطر والتعثرات مع السبب وخيارَي حل "
                "وتوصية 6) القرارات المطلوبة 7) الالتزامات والطلبات المالية 8) المعلومات المهمة "
                "والفرص 9) ما يحتاج تدخل عبدالرحمن اليوم. إذا لم توجد بيانات فاكتب: لا توجد بيانات "
                "مؤكدة. لا تستخدم جداول Markdown ولا تتجاوز 3000 حرف."
            )
            context = (
                "OPERATIONAL STATE (authoritative for machine-created operational records):\n"
                + operational_context
                + "\n\nSHEETS CHANGE DISCOVERY:\n"
                + compact_discovery(discovery, limit=4500)
                + "\n\nMANUAL SHEETS EVIDENCE / PROJECTION:\n"
                + compact_context(live, limit=4500)
            )

            answer, _, _, _ = bot.ask_bedrock(chat_id, prompt, sheet_context=context)

            dashboard_updated = True
            try:
                upsert_metrics({
                    "آخر تحديث للملخص التنفيذي": bot._now(),
                    "ملخص المدير الشخصي": answer[:5000],
                    "تغييرات جديدة منذ آخر Brief": discovery["stats"]["new_or_changed"],
                    "عناصر أزيلت أو أغلقت": discovery["stats"]["removed_or_resolved"],
                    "قرارات تحتاج مراجعة": len(operational.get("decision_requests", [])),
                    "مخاطر وتعثرات مكتشفة": len(discovery["blockers_and_risks"]),
                })
            except Exception as exc:
                dashboard_updated = False
                print(f"Executive brief dashboard update error: {exc}", flush=True)

            try:
                save_snapshot(normalize_snapshot(live))
            except Exception as exc:
                print(f"Brief snapshot save warning: {exc}", flush=True)

            status = (
                "\n\n✅ تم إنشاء الـBrief من StateStore وتحديث Executive_Brief كـprojection."
                if dashboard_updated
                else "\n\n⚠️ تم إنشاء الـBrief من StateStore، لكن projection إلى Executive_Brief لم ينجح."
            )
            bot.send(chat_id, answer + status)

        except Exception as exc:
            print(f"Brief generation error: {exc}", flush=True)
            bot.send(
                chat_id,
                "❌ تعذر إكمال /brief هذه المرة. لم تتم إعادة التنفيذ تلقائيًا لمنع التكرار. "
                "افحص /storage_status وحالة StateStore ثم أعد المحاولة.",
            )

    bot.command_brief = command_brief
    return command_brief

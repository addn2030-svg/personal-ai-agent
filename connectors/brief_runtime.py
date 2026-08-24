# -*- coding: utf-8 -*-
"""Resilient /brief runtime for Telegram webhook mode.

Keeps P0 lightweight: one Sheets snapshot, bounded AI context, graceful fallback,
and no exception propagation that would cause Telegram to redeliver the same update.
"""
from __future__ import annotations


def install(bot):
    """Replace telegram_bot.command_brief with the resilient implementation."""

    def command_brief(chat_id: int):
        bot.send(chat_id, "🧠 أنفّذ دورة الاكتشاف وأقارنها بآخر Brief Snapshot...")
        try:
            from connectors.brief_discovery import (
                compact_discovery,
                discover,
                normalize_snapshot,
                save_snapshot,
            )
            from connectors.sheet_intelligence import compact_context, snapshot, upsert_metrics

            # One bounded read only. The previous implementation fetched Sheets twice
            # (snapshot + _sheet_context), which increased timeout risk substantially.
            live = snapshot(max_rows=80, max_cols=16)
            discovery = discover(live, persist=False)

            prompt = (
                "أنشئ Executive Brief عربيًا مختصرًا بصفتك مدير أعمال عبدالرحمن. "
                "استخدم فقط الأدلة المرفقة وافصل المؤكد عن الاستنتاج. رتّب النتيجة إلى: "
                "1) أهم 3 أولويات 2) التغييرات منذ آخر Snapshot 3) المهام الناقصة "
                "4) المواعيد القادمة 5) المخاطر والتعثرات مع السبب وخيارَي حل وتوصية "
                "6) القرارات المطلوبة 7) الالتزامات والطلبات المالية "
                "8) المعلومات المهمة والفرص 9) ما يحتاج تدخل عبدالرحمن اليوم. "
                "إذا لم توجد بيانات لقسم فاكتب: لا توجد بيانات مؤكدة. "
                "اذكر اسم الشيت ورقم الصف عند الإمكان. لا تستخدم جداول Markdown، "
                "ولا تتجاوز 3000 حرف."
            )
            context = (
                "PRE-BRIEF DISCOVERY:\n"
                + compact_discovery(discovery, limit=5500)
                + "\n\nCURRENT SHEETS SNAPSHOT:\n"
                + compact_context(live, limit=5500)
            )

            answer, _, _, _ = bot.ask_bedrock(chat_id, prompt, sheet_context=context)

            dashboard_updated = True
            try:
                upsert_metrics({
                    "آخر تحديث للملخص التنفيذي": bot._now(),
                    "ملخص المدير الشخصي": answer[:5000],
                    "تغييرات جديدة منذ آخر Brief": discovery["stats"]["new_or_changed"],
                    "عناصر أزيلت أو أغلقت": discovery["stats"]["removed_or_resolved"],
                    "قرارات تحتاج مراجعة": len(discovery["decisions_required"]),
                    "مخاطر وتعثرات مكتشفة": len(discovery["blockers_and_risks"]),
                })
            except Exception as exc:  # Dashboard failure must not discard the brief.
                dashboard_updated = False
                print(f"Executive brief dashboard update error: {exc}", flush=True)

            try:
                save_snapshot(normalize_snapshot(live))
            except Exception as exc:
                print(f"Brief snapshot save warning: {exc}", flush=True)

            status = (
                "\n\n✅ تم إنشاء الـBrief وتحديث Executive_Brief."
                if dashboard_updated
                else "\n\n⚠️ تم إنشاء الـBrief، لكن تحديث Executive_Brief لم ينجح هذه المرة."
            )
            bot.send(chat_id, answer + status)

        except Exception as exc:
            # Important: do not re-raise. In webhook mode a re-raise can cause Telegram
            # to redeliver the same command and duplicate the progress message.
            print(f"Brief generation error: {exc}", flush=True)
            bot.send(
                chat_id,
                "❌ تعذر إكمال /brief هذه المرة. تم إيقاف إعادة التنفيذ التلقائي لمنع التكرار. "
                "استخدم /storage_status ثم أعد /brief بعد التأكد من اتصال Google Sheets.",
            )

    bot.command_brief = command_brief
    return command_brief

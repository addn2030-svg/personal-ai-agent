# -*- coding: utf-8 -*-
"""Install Executive Brief signal discovery onto the existing Telegram /brief path."""
from __future__ import annotations

from connectors import executive_signals

_INSTALLED = False


def install():
    global _INSTALLED
    if _INSTALLED:
        return

    from connectors import telegram_bot_legacy as legacy

    def command_brief(chat_id: int):
        """Generate a StateStore + Sheets brief that also preserves non-task executive context."""
        legacy.send(chat_id, "🧠 أكتشف التغييرات والقواعد التنفيذية وأقارنها بآخر Brief Snapshot...")
        from connectors.brief_discovery import (
            compact_discovery, discover, normalize_snapshot, save_snapshot,
        )
        from connectors.sheet_intelligence import snapshot, upsert_metrics

        live = snapshot(max_rows=120, max_cols=20)
        discovery = discover(live, persist=False)
        state_signals = executive_signals.state_signals(limit=25)
        compact_state = executive_signals.compact_state_signals(limit_chars=7000)

        prompt = (
            "أنشئ Executive Brief عربيًا مختصرًا بصفتك مدير أعمال عبدالرحمن. "
            "استخدم فقط الأدلة المرفقة، وافصل المؤكد عن الاستنتاج وعن USER_INPUT غير المرقى إلى حقيقة دائمة. "
            "لا تختزل الإدارة في المهام فقط: اعتبر القواعد التشغيلية والقيود والالتزامات ومعايير القرار "
            "والحدود المالية واللوجستيات وتغيّر حالة الأنظمة معلومات تنفيذية مهمة حتى لو لم تُصنّف TASK. "
            "نظّم النتيجة إلى: 1) أهم 3 أولويات 2) التغييرات منذ آخر Snapshot "
            "3) المهام الناقصة 4) المواعيد القادمة 5) المخاطر والتعثرات مع السبب وخيارَي حل وتوصية "
            "6) القرارات المطلوبة 7) الالتزامات والطلبات المالية "
            "8) المعلومات المهمة والفرص 9) القواعد والقيود التشغيلية واللوجستية "
            "10) ما يحتاج تدخل عبدالرحمن اليوم. "
            "إذا وجدت قاعدة وصول مثل الوصول قبل وقت محدد وربط الانطلاق بمدة الطريق، فاحفظ وقت الوصول كقيد مؤكد. "
            "لا تخترع مدة الطريق ولا وقت الانطلاق: احسب الانطلاق فقط إذا وُجدت مدة طريق مؤكدة في الأدلة؛ "
            "وإلا اذكر أن الحساب ديناميكي ويحتاج مدة الطريق الحية. لا تضف buffer غير مذكور. "
            "إذا لم توجد بيانات لقسم فاكتب: لا توجد بيانات مؤكدة. "
            "اذكر source_ref أو اسم الشيت ورقم الصف عند الإمكان. "
            "صيغة الإخراج لتيليجرام: نص عربي واضح، عناوين قصيرة مع رموز، ونقاط مرقمة فقط. "
            "ممنوع جداول Markdown وممنوع الرموز # و| و**. لا تتجاوز 3400 حرف وادمج العناصر المتشابهة."
        )
        context = (
            "PRE-BRIEF SHEET DISCOVERY:\n" + compact_discovery(discovery)
            + "\n\nSTATESTORE EXECUTIVE SIGNALS (read-only evidence; preserve evidence_status):\n" + compact_state
            + "\n\nCURRENT SHEETS SNAPSHOT:\n" + legacy._sheet_context()
        )
        answer, _, _, _ = legacy.ask_bedrock(chat_id, prompt, sheet_context=context)

        dashboard_updated = True
        try:
            upsert_metrics({
                "آخر تحديث للملخص التنفيذي": legacy._now(),
                "ملخص المدير الشخصي": answer[:5000],
                "تغييرات جديدة منذ آخر Brief": discovery["stats"]["new_or_changed"],
                "عناصر أزيلت أو أغلقت": discovery["stats"]["removed_or_resolved"],
                "قرارات تحتاج مراجعة": len(discovery["decisions_required"]),
                "مخاطر وتعثرات مكتشفة": len(discovery["blockers_and_risks"]),
                "إشارات تنفيذية مهمة": discovery["stats"].get("executive_signals", 0) + len(state_signals),
                "قواعد لوجستية مكتشفة": discovery["stats"].get("logistics_rules", 0)
                    + sum(1 for x in state_signals if "LOGISTICS_RULE" in x.get("categories", [])),
            })
        except Exception as exc:
            dashboard_updated = False
            print(f"Executive brief dashboard update error: {exc}", flush=True)

        save_snapshot(normalize_snapshot(live))
        status = (
            "\n\n✅ تم تحديث Executive_Brief وحفظ Snapshot وإشارات المدير."
            if dashboard_updated else
            "\n\n⚠️ تم إنشاء الملخص وحفظ Snapshot، لكن تحديث Executive_Brief عبر البوابة لم يكتمل."
        )
        legacy.send(chat_id, answer + status)

    legacy.command_brief = command_brief
    _INSTALLED = True

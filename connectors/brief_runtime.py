# -*- coding: utf-8 -*-
"""Resilient /brief runtime for Telegram webhook mode.

The brief should remain useful even when the model provider is temporarily down.
Google Sheets/discovery failures are reported with the exact failing stage, while
model failures fall back to a deterministic evidence-only brief.
"""
from __future__ import annotations


def _safe_error(exc: Exception) -> str:
    try:
        from connectors.model_gateway import _safe_error as model_safe_error
        return model_safe_error(exc)
    except Exception:
        return str(exc).replace("\n", " ")[:240]


def _item_line(item: dict) -> str:
    values = [str(x).strip() for x in (item.get("values") or []) if str(x).strip()]
    preview = " | ".join(values[:4])[:230] or "بدون وصف واضح"
    date = f" | {item.get('date')}" if item.get("date") else ""
    return f"• {item.get('sheet', '—')} — صف {item.get('row', '—')}{date}: {preview}"


def _section(title: str, items: list[dict], limit: int = 3) -> list[str]:
    lines = [title]
    if not items:
        lines.append("• لا توجد بيانات مؤكدة.")
        return lines
    lines.extend(_item_line(item) for item in items[:limit])
    return lines


def _deterministic_brief(discovery: dict) -> str:
    """Evidence-only fallback when no model provider can answer."""
    stats = discovery.get("stats") or {}
    blockers = discovery.get("blockers_and_risks") or []
    decisions = discovery.get("decisions_required") or []
    incomplete = discovery.get("missing_or_incomplete") or []
    upcoming = discovery.get("upcoming_dates") or []
    important = discovery.get("important_information") or []
    changed = discovery.get("new_or_changed") or []

    priorities = []
    seen = set()
    for group in (blockers, decisions, upcoming, incomplete, changed):
        for item in group:
            key = (item.get("sheet"), item.get("row"))
            if key in seen:
                continue
            seen.add(key)
            priorities.append(item)
            if len(priorities) >= 3:
                break
        if len(priorities) >= 3:
            break

    lines = [
        "⚙️ Executive Brief تشغيلي — Evidence Only",
        "طبقة AI غير متاحة مؤقتًا؛ هذا الملخص مستخرج مباشرة من الشيت بدون استنتاجات مولدة.",
        "",
    ]
    lines += _section("1) أهم الأولويات المؤكدة", priorities)
    lines += [
        "",
        "2) التغييرات منذ آخر Snapshot",
        f"• جديد/متغير: {stats.get('new_or_changed', 0)}",
        f"• أزيل/أغلق: {stats.get('removed_or_resolved', 0)}",
        f"• إجمالي الصفوف المفهرسة: {stats.get('rows', 0)}",
        "",
    ]
    lines += _section("3) المواعيد القادمة", upcoming)
    lines += [""]
    lines += _section("4) المخاطر والتعثرات", blockers)
    lines += [""]
    lines += _section("5) القرارات المطلوبة", decisions)
    lines += [""]
    lines += _section("6) المهام الناقصة/غير المكتملة", incomplete)
    lines += [""]
    lines += _section("7) المعلومات المهمة والفرص", important)
    return "\n".join(lines)[:3000]


def install(bot):
    """Replace telegram_bot.command_brief with the resilient implementation."""

    def command_brief(chat_id: int):
        bot.send(chat_id, "🧠 أنفّذ دورة الاكتشاف وأقارنها بآخر Brief Snapshot...")
        stage = "init"
        try:
            from connectors.brief_discovery import (
                compact_discovery,
                discover,
                normalize_snapshot,
                save_snapshot,
            )
            from connectors.sheet_intelligence import compact_context, snapshot, upsert_metrics

            stage = "sheets_snapshot"
            live = snapshot(max_rows=80, max_cols=16)

            stage = "discovery"
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

            ai_ok = True
            ai_error = ""
            stage = "model"
            try:
                answer, _, _, _ = bot.ask_bedrock(chat_id, prompt, sheet_context=context)
            except Exception as exc:
                ai_ok = False
                ai_error = _safe_error(exc)
                print(f"Brief model error: {ai_error}", flush=True)
                answer = _deterministic_brief(discovery)

            dashboard_updated = True
            stage = "dashboard_update"
            try:
                metrics = {
                    "آخر تحديث للملخص التنفيذي": bot._now(),
                    "ملخص المدير الشخصي": answer[:5000],
                    "تغييرات جديدة منذ آخر Brief": discovery["stats"]["new_or_changed"],
                    "عناصر أزيلت أو أغلقت": discovery["stats"]["removed_or_resolved"],
                    "قرارات تحتاج مراجعة": len(discovery["decisions_required"]),
                    "مخاطر وتعثرات مكتشفة": len(discovery["blockers_and_risks"]),
                    "حالة طبقة AI": "OK" if ai_ok else "FALLBACK_EVIDENCE_ONLY",
                }
                upsert_metrics(metrics)
            except Exception as exc:
                dashboard_updated = False
                print(f"Executive brief dashboard update error: {_safe_error(exc)}", flush=True)

            stage = "snapshot_save"
            try:
                save_snapshot(normalize_snapshot(live))
            except Exception as exc:
                print(f"Brief snapshot save warning: {_safe_error(exc)}", flush=True)

            status_parts = []
            if ai_ok:
                status_parts.append("✅ طبقة AI أنشأت الـBrief.")
            else:
                status_parts.append(
                    "⚠️ تعذر استدعاء طبقة AI؛ تم إرسال Brief تشغيلي من الأدلة المباشرة بدل إسقاط الأمر."
                )
                status_parts.append("AI error: " + ai_error)
            status_parts.append(
                "✅ تم تحديث Executive_Brief."
                if dashboard_updated
                else "⚠️ لم ينجح تحديث Executive_Brief، لكن تم الحفاظ على نتيجة الـBrief."
            )
            bot.send(chat_id, answer + "\n\n" + "\n".join(status_parts))

        except Exception as exc:
            # Never re-raise in webhook mode; Telegram redelivery can duplicate work.
            safe = _safe_error(exc)
            print(f"Brief generation error at {stage}: {safe}", flush=True)
            bot.send(
                chat_id,
                "❌ تعذر إكمال /brief.\n"
                f"Stage: {stage}\n"
                f"Error: {safe}\n\n"
                "لن أعيد التنفيذ تلقائيًا حتى لا تتكرر العملية.",
            )

    bot.command_brief = command_brief
    return command_brief

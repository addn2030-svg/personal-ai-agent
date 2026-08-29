# -*- coding: utf-8 -*-
"""Production Telegram webhook runtime with direct-first Google Sheets access.

This runtime is the Railway entrypoint. Critical production commands that must not
fall back to the legacy Apps Script gateway are overridden here.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import telegram_webhook as webhook
from connectors import google_credentials

bot = webhook.bot
_fallback_append = bot._append
_direct_service = None


def _direct_ready() -> bool:
    return bool(bot.GOOGLE_SHEET_ID and google_credentials.service_account_info())


def _service():
    global _direct_service
    if _direct_service is not None:
        return _direct_service
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing or invalid")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _direct_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _direct_service


def _direct_append(tab: str, row: list):
    safe_tab = str(tab).replace("'", "''")
    return _service().spreadsheets().values().append(
        spreadsheetId=bot.GOOGLE_SHEET_ID,
        range=f"'{safe_tab}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def _append_direct_first(tab: str, row: list):
    direct_error = None
    if _direct_ready():
        for attempt, delay in enumerate((0, 1, 2), start=1):
            if delay:
                time.sleep(delay)
            try:
                _direct_append(tab, row)
                return
            except Exception as exc:  # connector boundary
                direct_error = exc
                print(
                    f"Sheets direct write attempt {attempt}/3 failed for {tab}: {str(exc)[:180]}",
                    flush=True,
                )

    try:
        return _fallback_append(tab, row)
    except Exception as fallback_error:
        if direct_error is not None:
            raise RuntimeError(
                "Google Sheets direct write failed; Apps Script fallback also failed: "
                + str(fallback_error)[:220]
            ) from fallback_error
        raise


bot._append = _append_direct_first


def _direct_error_text(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    prefix = f"HTTP {status}: " if status else ""
    text = str(exc).replace("\n", " ")
    return prefix + text[:320]


def _command_storage_status(chat_id: int):
    """Diagnose the direct Sheets route without hiding it behind Apps Script fallback."""
    info = google_credentials.service_account_info()
    if not info or not bot.GOOGLE_SHEET_ID:
        bot.send(
            chat_id,
            "❌ Direct Google Sheets غير مهيأ.\n"
            "GOOGLE_SERVICE_ACCOUNT_JSON أو GOOGLE_SHEET_ID مفقود/غير صالح.",
        )
        return

    email = str(info.get("client_email") or "unknown")
    try:
        meta = _service().spreadsheets().get(
            spreadsheetId=bot.GOOGLE_SHEET_ID,
            fields="spreadsheetId,properties.title",
        ).execute()
    except Exception as exc:
        bot.send(
            chat_id,
            "❌ Direct Google Sheets: لا يستطيع فتح الشيت.\n"
            f"Service account: {email}\n"
            f"Error: {_direct_error_text(exc)}\n\n"
            "الحل المتوقع: شارك Google Sheet مع Service account أعلاه بصلاحية Editor.",
        )
        return

    try:
        _direct_append(
            bot.STATUS_TAB,
            [bot._now(), "STORAGE_TEST", "OK", "Direct Sheets API connected", "v2.0", bot.AWS_REGION, bot.BEDROCK_MODEL_ID, bot._now()],
        )
    except Exception as exc:
        bot.send(
            chat_id,
            "⚠️ Direct Google Sheets: يستطيع فتح الشيت لكن فشل اختبار الكتابة.\n"
            f"Sheet: {meta.get('properties', {}).get('title', 'connected')}\n"
            f"Service account: {email}\n"
            f"Error: {_direct_error_text(exc)}",
        )
        return

    bot.send(
        chat_id,
        "💾 Google Sheets Direct: connected ✅\n"
        f"Sheet: {meta.get('properties', {}).get('title', 'connected')}\n"
        f"Service account: {email}\n"
        "اختبار القراءة والكتابة نجح.",
    )


bot.command_storage_status = _command_storage_status


# ---------------------------------------------------------------------------
# Direct Brief v2
# ---------------------------------------------------------------------------
# This command intentionally does NOT import connectors.sheet_intelligence and
# never calls GOOGLE_SHEETS_WEBHOOK_URL / Apps Script. It is fully isolated from
# the legacy brief stack and uses the already verified Service Account route.

_BRIEF_PRIORITY_TABS = [
    "Projects",
    "خطة الإنجاز والمهام",
    "Smart_Inbox",
    "Waiting_For",
    "Blockers",
    "Executive_Brief",
    "التطوير الشخصي",
    "الهدف المالي E-S-B-I",
    "التحليل المالي المختصر",
    "تعليمات تجاوز نقاط الضعف",
    "المصادر والتعلم العلمي",
    "القرارات",
    "لوحة التحكم",
]
_BRIEF_EXCLUDED_TABS = {"Calc_Data", "مدخلات الوكيل", "محادثات الوكيل", "حالة الوكيل"}


def _column_letter(number: int) -> str:
    number = max(1, int(number))
    text = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        text = chr(65 + remainder) + text
    return text


def _direct_brief_snapshot(max_rows: int = 80, max_cols: int = 16) -> dict:
    """Read the brief source tabs in one direct Sheets API batch request."""
    if not _direct_ready():
        raise RuntimeError("Direct Service Account route is not configured")

    meta = _service().spreadsheets().get(
        spreadsheetId=bot.GOOGLE_SHEET_ID,
        fields="sheets.properties(title,gridProperties(rowCount,columnCount))",
    ).execute()
    sheets = []
    for item in meta.get("sheets", []):
        props = item.get("properties") or {}
        grid = props.get("gridProperties") or {}
        title = str(props.get("title") or "")
        if not title:
            continue
        sheets.append({
            "title": title,
            "rows": int(grid.get("rowCount") or max_rows),
            "columns": int(grid.get("columnCount") or max_cols),
        })

    by_title = {item["title"]: item for item in sheets}
    selected = [by_title[t] for t in _BRIEF_PRIORITY_TABS if t in by_title]
    selected += [
        item for item in sheets
        if item["title"] not in _BRIEF_PRIORITY_TABS
        and item["title"] not in _BRIEF_EXCLUDED_TABS
    ]
    selected = selected[:18]
    if not selected:
        raise RuntimeError("No eligible sheet tabs found for Direct Brief v2")

    ranges = []
    for item in selected:
        row_limit = max(1, min(max_rows, item["rows"]))
        col_limit = max(1, min(max_cols, item["columns"]))
        end_col = _column_letter(col_limit)
        safe_title = item["title"].replace("'", "''")
        ranges.append(f"'{safe_title}'!A1:{end_col}{row_limit}")

    response = _service().spreadsheets().values().batchGet(
        spreadsheetId=bot.GOOGLE_SHEET_ID,
        ranges=ranges,
        majorDimension="ROWS",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()

    value_ranges = response.get("valueRanges") or []
    out = {}
    for item, result in zip(selected, value_ranges):
        values = result.get("values") or []
        if values:
            out[item["title"]] = [row[:max_cols] for row in values]
    if not out:
        raise RuntimeError("Direct Sheets read succeeded but returned no brief data")
    return out


def _brief_item_line(item: dict) -> str:
    values = [str(x).strip() for x in (item.get("values") or []) if str(x).strip()]
    preview = " | ".join(values[:4])[:220] or "بدون وصف واضح"
    date = f" | {item.get('date')}" if item.get("date") else ""
    return f"• {item.get('sheet', '—')} — صف {item.get('row', '—')}{date}: {preview}"


def _brief_section(title: str, items: list[dict], limit: int = 3) -> list[str]:
    lines = [title]
    if not items:
        lines.append("• لا توجد بيانات مؤكدة.")
        return lines
    lines.extend(_brief_item_line(item) for item in items[:limit])
    return lines


def _direct_evidence_brief(discovery: dict) -> str:
    """Useful fallback if all model providers are unavailable."""
    stats = discovery.get("stats") or {}
    blockers = discovery.get("blockers_and_risks") or []
    decisions = discovery.get("decisions_required") or []
    upcoming = discovery.get("upcoming_dates") or []
    incomplete = discovery.get("missing_or_incomplete") or []
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

    lines = ["⚙️ Executive Brief — Direct Evidence Mode", ""]
    lines += _brief_section("1) أهم الأولويات", priorities)
    lines += [
        "",
        "2) التغييرات منذ آخر Snapshot",
        f"• جديد/متغير: {stats.get('new_or_changed', 0)}",
        f"• أزيل/أغلق: {stats.get('removed_or_resolved', 0)}",
        f"• إجمالي الصفوف المفهرسة: {stats.get('rows', 0)}",
        "",
    ]
    lines += _brief_section("3) المواعيد القادمة", upcoming)
    lines += [""] + _brief_section("4) المخاطر والتعثرات", blockers)
    lines += [""] + _brief_section("5) القرارات المطلوبة", decisions)
    lines += [""] + _brief_section("6) المهام الناقصة", incomplete)
    lines += [""] + _brief_section("7) المعلومات المهمة والفرص", important)
    return "\n".join(lines)[:3000]


def _direct_upsert_brief_metrics(metrics: dict, sheet: str = "Executive_Brief") -> int:
    """Write dashboard metrics directly; no webhook or sheet_intelligence."""
    clean = {str(k)[:160]: str(v)[:5000] for k, v in metrics.items()}
    safe_sheet = sheet.replace("'", "''")
    current = _service().spreadsheets().values().get(
        spreadsheetId=bot.GOOGLE_SHEET_ID,
        range=f"'{safe_sheet}'!A:B",
    ).execute().get("values", [])
    labels = {str(row[0]): i + 1 for i, row in enumerate(current) if row}
    next_row = max(len(current) + 1, 1)
    updates = []
    for label, value in clean.items():
        row = labels.get(label)
        if row is None:
            row = next_row
            next_row += 1
        updates.append({
            "range": f"'{safe_sheet}'!A{row}:B{row}",
            "values": [[label, value]],
        })
    if updates:
        _service().spreadsheets().values().batchUpdate(
            spreadsheetId=bot.GOOGLE_SHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
    return len(updates)


def _command_brief_v2(chat_id: int):
    bot.send(chat_id, "🧠 Direct Brief v2: أقرأ Google Sheets مباشرة وأبني الملخص...")
    stage = "direct_snapshot"
    try:
        from connectors.brief_discovery import (
            compact_discovery,
            discover,
            normalize_snapshot,
            save_snapshot,
        )

        live = _direct_brief_snapshot(max_rows=80, max_cols=16)
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
            "DIRECT BRIEF V2 DISCOVERY:\n"
            + compact_discovery(discovery, limit=5500)
            + "\n\nDIRECT GOOGLE SHEETS SNAPSHOT:\n"
            + json.dumps(live, ensure_ascii=False, separators=(",", ":"))[:5500]
        )

        ai_ok = True
        ai_error = ""
        stage = "model"
        try:
            answer, _, _, _ = bot.ask_bedrock(chat_id, prompt, sheet_context=context)
        except Exception as exc:
            ai_ok = False
            ai_error = _direct_error_text(exc)
            print(f"Direct Brief v2 model warning: {ai_error}", flush=True)
            answer = _direct_evidence_brief(discovery)

        dashboard_ok = True
        stage = "direct_dashboard_write"
        try:
            _direct_upsert_brief_metrics({
                "آخر تحديث للملخص التنفيذي": bot._now(),
                "ملخص المدير الشخصي": answer[:5000],
                "تغييرات جديدة منذ آخر Brief": discovery["stats"]["new_or_changed"],
                "عناصر أزيلت أو أغلقت": discovery["stats"]["removed_or_resolved"],
                "قرارات تحتاج مراجعة": len(discovery["decisions_required"]),
                "مخاطر وتعثرات مكتشفة": len(discovery["blockers_and_risks"]),
                "Brief Runtime": "DIRECT_V2",
                "حالة طبقة AI": "OK" if ai_ok else "EVIDENCE_FALLBACK",
            })
        except Exception as exc:
            dashboard_ok = False
            print(f"Direct Brief v2 dashboard warning: {_direct_error_text(exc)}", flush=True)

        stage = "snapshot_save"
        snapshot_ok = True
        try:
            save_snapshot(normalize_snapshot(live))
        except Exception as exc:
            snapshot_ok = False
            print(f"Direct Brief v2 snapshot warning: {_direct_error_text(exc)}", flush=True)

        notes = ["✅ Direct Brief v2 استخدم Google Sheets API مباشرة — بدون Apps Script/Webhook."]
        notes.append("✅ طبقة AI عملت." if ai_ok else "⚠️ طبقة AI لم تعمل؛ تم استخدام Evidence Mode.")
        if not ai_ok:
            notes.append("AI error: " + ai_error[:220])
        notes.append("✅ تم تحديث Executive_Brief مباشرة." if dashboard_ok else "⚠️ تعذر تحديث Executive_Brief.")
        if not snapshot_ok:
            notes.append("⚠️ لم يتم حفظ Snapshot المحلي، لكن الملخص نفسه اكتمل.")
        bot.send(chat_id, answer + "\n\n" + "\n".join(notes))

    except Exception as exc:
        safe = _direct_error_text(exc)
        print(f"Direct Brief v2 fatal error at {stage}: {safe}", flush=True)
        bot.send(
            chat_id,
            "❌ Direct Brief v2 تعذر إكماله.\n"
            f"Stage: {stage}\n"
            f"Error: {safe}\n\n"
            "هذا المسار لا يستخدم Apps Script أو Webhook.",
        )


# Override every older /brief implementation at the actual Railway entrypoint.
bot.command_brief = _command_brief_v2


def run():
    state = google_credentials.status()
    print(
        "Sheets production route: "
        + ("direct-first" if _direct_ready() else "Apps-Script-only")
        + f" | service_account={state.get('source')} valid={state.get('valid')}",
        flush=True,
    )
    print("Direct Brief v2 override: active", flush=True)
    webhook.run()


if __name__ == "__main__":
    run()

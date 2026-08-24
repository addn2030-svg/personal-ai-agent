# -*- coding: utf-8 -*-
"""Secure Telegram + Claude/Bedrock + Google Sheets intake pipeline."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
GOOGLE_SHEETS_WEBHOOK_SECRET = os.environ.get("GOOGLE_SHEETS_WEBHOOK_SECRET", "").strip()
INTAKE_TAB = os.environ.get("GOOGLE_INTAKE_SHEET", "مدخلات الوكيل").strip()
CONVERSATION_TAB = os.environ.get("GOOGLE_CONVERSATIONS_SHEET", "محادثات الوكيل").strip()
STATUS_TAB = os.environ.get("GOOGLE_STATUS_SHEET", "حالة الوكيل").strip()
OWNER_FILE = BASE / "data" / ".telegram-owner-chat-id"
API_BASE = f"https://api.telegram.org/bot{TOKEN}"
_SHEETS_SERVICE = None
_PENDING_SHEET_UPDATES = {}

SYSTEM_PROMPT = """You are Abdulrahman AI OS, the private Chief of Staff for
Abdulrahman Bakor Howsawy, Senior Physical Therapist and Head of Rehabilitation.
Answer in Arabic by default and in English when the user writes in English.
Be concise, practical, and distinguish confirmed facts from assumptions.
Authorized Telegram messages and your answers are logged to Abdulrahman's
private Google Sheet after privacy redaction; never claim that nothing is saved.
Never claim autonomous self-learning: durable knowledge changes require review.
Never reveal credentials, private contact details, or patient identities.
For clinical questions, provide decision support only, identify red flags, and
state that final clinical decisions require professional review. External actions
and sensitive decisions always require Abdulrahman's approval.
"""


def _now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")


def api(method: str, payload: dict | None = None, timeout: int = 60):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    body = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(f"{API_BASE}/{method}", data=body)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data.get("result")


def send(chat_id: int, text: str):
    text = str(text)
    for start in range(0, len(text), 3800):
        api("sendMessage", {"chat_id": chat_id, "text": text[start:start + 3800]})


def _owner_id():
    if ALLOWED_CHAT_ID:
        return ALLOWED_CHAT_ID
    try:
        return OWNER_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authorized(chat_id: int, chat_type: str):
    owner = _owner_id()
    if owner:
        return str(chat_id) == owner
    if chat_type != "private":
        return False
    OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
    return True


def _bedrock_configured():
    auth = bool(
        os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
    )
    return auth and bool(AWS_REGION) and bool(BEDROCK_MODEL_ID)


def _sheets_configured():
    service_account_ok = bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON)
    webhook_ok = bool(GOOGLE_SHEETS_WEBHOOK_URL and GOOGLE_SHEETS_WEBHOOK_SECRET)
    return service_account_ok or webhook_ok


def _sheets():
    global _SHEETS_SERVICE
    if _SHEETS_SERVICE is not None:
        return _SHEETS_SERVICE
    if not _sheets_configured():
        raise RuntimeError("Google Sheets variables are not configured")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _SHEETS_SERVICE = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _SHEETS_SERVICE


def _append(tab: str, row: list):
    if GOOGLE_SHEETS_WEBHOOK_URL and GOOGLE_SHEETS_WEBHOOK_SECRET:
        payload = json.dumps(
            {"secret": GOOGLE_SHEETS_WEBHOOK_SECRET, "tab": tab, "row": row},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            GOOGLE_SHEETS_WEBHOOK_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        result = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError("Sheets webhook: " + str(result.get("error", "unknown error")))
        return
    _sheets().spreadsheets().values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"'{tab}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def _language(text: str):
    return "ar" if re.search(r"[\u0600-\u06FF]", text or "") else "en"


def _clinical_hint(text: str):
    return bool(re.search(
        r"patient|مريض|mrn|medical record|رقم الملف|diagnosis|تشخيص|clinical|سريري|"
        r"pain|ألم|علاج|دواء|عملية|surgery|symptom|عرض مرضي",
        text or "", re.I
    ))


def _category(text: str, kind: str = "TEXT"):
    t = text or ""
    if _clinical_hint(t):
        return "CLINICAL_PRIVATE"
    if kind in {"DOCUMENT", "PHOTO", "VOICE", "AUDIO", "VIDEO"}:
        return "DOCUMENT"
    if re.search(r"decision|decide|approve|قرار|اعتماد|موافقة", t, re.I):
        return "DECISION"
    if re.search(r"waiting|pending|follow.?up|انتظار|معلق|متابعة", t, re.I):
        return "WAITING_FOR"
    if re.search(r"task|todo|remind|مهمة|تذكير|نفذ|اعمل", t, re.I):
        return "TASK"
    if re.search(r"idea|suggest|فكرة|اقتراح", t, re.I):
        return "IDEA"
    return "GENERAL"


def _redact(text: str):
    value = text or ""
    value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL_REDACTED]", value, flags=re.I)
    value = re.sub(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)", "[PHONE_REDACTED]", value)
    value = re.sub(
        r"(?i)(mrn|medical record|رقم الملف|رقم الهوية|id number)\s*[:#-]?\s*[A-Z0-9-]+",
        r"\1: [IDENTIFIER_REDACTED]",
        value,
    )
    return value


def _message_payload(message: dict):
    text = (message.get("text") or message.get("caption") or "").strip()
    if message.get("voice"):
        return text or "[VOICE_PENDING_TRANSCRIPTION]", "VOICE", message["voice"].get("file_id", "")
    if message.get("audio"):
        return text or "[AUDIO_PENDING_TRANSCRIPTION]", "AUDIO", message["audio"].get("file_id", "")
    if message.get("document"):
        name = message["document"].get("file_name", "document")
        return text or f"[DOCUMENT: {name}]", "DOCUMENT", message["document"].get("file_id", "")
    if message.get("photo"):
        return text or "[PHOTO]", "PHOTO", message["photo"][-1].get("file_id", "")
    if message.get("video"):
        return text or "[VIDEO]", "VIDEO", message["video"].get("file_id", "")
    return text, "TEXT", ""


def _local_capture(text: str, message: dict, kind: str):
    try:
        from unified_inbox import add, classify

        ref = f"telegram:{message.get('message_id', '')}"
        iid = add(
            "TELEGRAM", text, kind=kind, source_ref=ref,
            sensitive=_clinical_hint(text),
            metadata={"chat_id": str((message.get("chat") or {}).get("id", ""))},
        )
        category = _category(text, kind)
        if category != "GENERAL":
            classify(iid, category, "Specialist review required" if category == "CLINICAL_PRIVATE" else "Review")
        return iid
    except Exception as exc:
        print(f"Local intake capture error: {exc}", flush=True)
        return f"TG-{(message.get('chat') or {}).get('id','')}-{message.get('message_id','')}"


def _save_intake(iid, message, text, kind, attachment, status, response_id="", error=""):
    category = _category(text, kind)
    privacy = "REDACTED" if category == "CLINICAL_PRIVATE" else "NORMAL"
    safe_text = _redact(text)
    row = [
        iid, _now(), "TELEGRAM", str((message.get("chat") or {}).get("id", "")),
        kind, safe_text, _language(text), category, privacy, status,
        response_id, _now() if status in {"COMPLETED", "ERROR"} else "",
        str(error)[:500], attachment, "",
    ]
    try:
        _append(INTAKE_TAB, row)
        return True
    except Exception as exc:
        print(f"Google intake save error: {exc}", flush=True)
        return False


def _save_conversation(cid, iid, question, answer, usage, latency_ms, status, error=""):
    clinical = _category(question) == "CLINICAL_PRIVATE"
    review = "PENDING" if clinical else "NOT_REQUIRED"
    safe_question = _redact(question)
    safe_answer = _redact(answer)
    row = [
        cid, iid, _now(), "AWS_BEDROCK", BEDROCK_MODEL_ID,
        safe_question, safe_answer,
        usage.get("inputTokens", ""), usage.get("outputTokens", ""),
        latency_ms, status, review, str(error)[:500],
    ]
    try:
        _append(CONVERSATION_TAB, row)
        return True
    except Exception as exc:
        print(f"Google conversation save error: {exc}", flush=True)
        return False


def _save_status(component, status, detail):
    try:
        _append(STATUS_TAB, [
            _now(), component, status, str(detail)[:1000], "v1.1",
            AWS_REGION, BEDROCK_MODEL_ID, _now(),
        ])
    except Exception as exc:
        print(f"Google status save error: {exc}", flush=True)


def ask_bedrock(chat_id: int, text: str, sheet_context: str = ""):
    if not _bedrock_configured():
        raise RuntimeError("AWS Bedrock variables are not configured")
    import boto3

    started = time.monotonic()
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    from agent_runtime import build_context, bedrock_messages
    context, sources = build_context(chat_id, text)
    if sheet_context:
        context += "\n\nLIVE GOOGLE SHEETS CONTEXT (read-only evidence):\n" + sheet_context
    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT + "\n\n" + context}],
        messages=bedrock_messages(chat_id, text),
        inferenceConfig={"maxTokens": 1200, "temperature": 0.2},
    )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    answer = "\n".join(block.get("text", "") for block in blocks if block.get("text"))
    if not answer:
        raise RuntimeError("Claude returned an empty response")
    return answer, response.get("usage", {}), int((time.monotonic() - started) * 1000), sources



def _sheet_context():
    from connectors.sheet_intelligence import compact_context
    return compact_context()


def command_sheet(chat_id: int):
    from connectors.sheet_intelligence import configured, metadata
    if not configured():
        send(chat_id, "❌ ربط Google Sheets غير مكتمل.")
        return
    rows = metadata()
    send(chat_id, "📊 الشيتات المتصلة:\n" + "\n".join(
        f"• {row['title']} ({row.get('rows', 0)}×{row.get('columns', 0)})" for row in rows
    ))


def command_find(chat_id: int, query: str):
    from connectors.sheet_intelligence import search
    if not query.strip():
        send(chat_id, "الاستخدام: /find كلمة البحث")
        return
    rows = search(query, 20)
    if not rows:
        send(chat_id, "لم أجد نتائج مطابقة.")
        return
    lines = [f"🔎 نتائج: {query}"]
    for row in rows:
        preview = " | ".join(map(str, row.get("values", [])))[:260]
        lines.append(f"• {row['sheet']} — صف {row['row']}: {preview}")
    send(chat_id, "\n".join(lines))


def command_pending(chat_id: int):
    send(chat_id, "🧠 أراجع الآن: ما القادم، ما غير مكتمل، السبب، والحل...")
    prompt = (
        "حلّل بيانات Google Sheets الحية كمدير أعمال عبدالرحمن. "
        "أعطني فقط: 1) القادم 2) غير المكتمل 3) السبب المدعوم بالبيانات "
        "4) الحل العملي 5) ما يحتاج قرارًا الآن. "
        "لا تخترع معلومات، واذكر اسم الشيت والصف عند الإمكان."
    )
    answer, _, _, _ = ask_bedrock(chat_id, prompt, sheet_context=_sheet_context())
    send(chat_id, answer)


def command_brief(chat_id: int):
    """
    /brief or /b
    Executive summary: today's priorities, meetings, overdue tasks, pending decisions,
    supervisor status, family alerts, with source tracking and sync time.
    """
    if not _sheets_configured():
        send(chat_id, "❌ ربط Google Sheets غير مكتمل.")
        return

    try:
        from connectors.sheet_intelligence import snapshot
        from connectors.google_workspace import calendar_window
        import datetime as dt

        started = dt.datetime.now()
        data = snapshot()
        today_iso = dt.date.today().isoformat()

        output = []
        output.append("📋 **البريف التنفيذي للعبدالرحمن**")
        output.append("")

        # 1. TODAY'S TOP 3 PRIORITIES
        output.append("🎯 **الأولويات (اليوم)**")
        if "خطة الإنجاز والمهام" in data:
            rows = data["خطة الإنجاز والمهام"]
            priorities = []
            for row in rows[1:]:
                if row and len(row) > 0 and row[0]:
                    # Check if due today or overdue
                    due_date_str = row[2] if len(row) > 2 else ""
                    status = row[3] if len(row) > 3 else ""
                    if status and status.lower() not in {"مكتمل", "completed"}:
                        priorities.append((row[0], due_date_str, status))

            if priorities:
                for i, (task, due, status) in enumerate(priorities[:3], 1):
                    output.append(f"{i}. {task} (حالة: {status})")
            else:
                output.append("✅ لا توجد مهام معلقة اليوم")
        else:
            output.append("⚠️ شيت المهام غير متاح")

        output.append("")

        # 2. TODAY'S CALENDAR MEETINGS
        output.append("📅 **الاجتماعات (اليوم)**")
        try:
            events = calendar_window(days_back=0, days_forward=1)
            today_events = [e for e in events if e['start'].startswith(today_iso)]

            if today_events:
                for event in today_events[:5]:
                    time_str = event['start'].split('T')[1][:5] if 'T' in event['start'] else ""
                    loc = f" @ {event['location']}" if event.get('location') else ""
                    output.append(f"• {event['summary']} ({time_str}){loc}")
            else:
                output.append("✅ لا توجد اجتماعات مجدولة اليوم")
        except Exception as e:
            output.append(f"⚠️ خطأ في القراءة: {str(e)[:80]}")

        output.append("")

        # 3. OVERDUE TASKS WITH OWNER, REASON, SOLUTION
        output.append("⚠️ **المتأخرات**")
        if "خطة الإنجاز والمهام" in data:
            rows = data["خطة الإنجاز والمهام"]
            overdue = []
            for row in rows[1:]:
                if row and len(row) > 3:
                    due_date_str = row[2] if len(row) > 2 else ""
                    status = row[3] if len(row) > 3 else ""
                    reason = row[4] if len(row) > 4 else ""
                    solution = row[5] if len(row) > 5 else ""
                    owner = row[6] if len(row) > 6 else "—"

                    if due_date_str and status and status.lower() not in {"مكتمل", "completed"}:
                        try:
                            due_dt = dt.datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                            if due_dt.date() < dt.date.today():
                                overdue.append((row[0], due_date_str[:10], owner, reason, solution))
                        except:
                            pass

            if overdue:
                for task, due, owner, reason, solution in overdue[:3]:
                    output.append(f"• {task}")
                    output.append(f"  الموعد: {due} | المالك: {owner}")
                    if reason:
                        output.append(f"  السبب: {reason}")
                    if solution:
                        output.append(f"  الحل: {solution}")
            else:
                output.append("✅ لا توجد مهام متأخرة")
        else:
            output.append("⚠️ شيت المهام غير متاح")

        output.append("")

        # 4. PENDING DECISIONS
        output.append("⏳ **القرارات المعلقة**")
        if "القرارات العالقة" in data:
            rows = data["القرارات العالقة"]
            pending = [r for r in rows[1:] if r and r[0]]

            if pending:
                for decision in pending[:3]:
                    due = f" (موعد: {decision[1]})" if len(decision) > 1 and decision[1] else ""
                    output.append(f"• {decision[0]}{due}")
            else:
                output.append("✅ لا توجد قرارات معلقة")
        else:
            output.append("⚠️ شيت القرارات غير متاح")

        output.append("")

        # 5. SUPERVISOR STATUS
        output.append("👥 **حالة المشرفين**")
        supervisors = [
            ("عبدالمجيد", "مشرف الرجال/الخارجية"),
            ("شهد", "مشرفة البنات/الخارجية"),
            ("سمية", "مشرفة التنويم/الداخلية"),
        ]

        if "حالة المشرفين" in data:
            rows = data["حالة المشرفين"]
            for idx, (name, role) in enumerate(supervisors):
                if idx + 1 < len(rows) and rows[idx + 1]:
                    status = rows[idx + 1][1] if len(rows[idx + 1]) > 1 else "—"
                    output.append(f"• {name}: {status}")
                else:
                    output.append(f"• {name}: —")
        else:
            output.append("⚠️ شيت المشرفين غير متاح")

        output.append("")

        # 6. FAMILY/TRANSPORT CONFLICTS
        output.append("👨‍👩‍👧‍👦 **التنسيق الأسري**")
        if "تنسيق الأسرة والسيارة" in data:
            rows = data["تنسيق الأسرة والسيارة"]
            conflicts = []
            for row in rows[1:]:
                if row and len(row) > 2 and ("تعارض" in str(row[2]).lower() or "conflict" in str(row[2]).lower()):
                    conflicts.append(row[2])

            if conflicts:
                for conflict in conflicts[:2]:
                    output.append(f"⚠️ {conflict}")
            else:
                output.append("✅ لا توجد تعارضات في التنسيق")
        else:
            output.append("⚠️ شيت التنسيق غير متاح")

        output.append("")

        # 7. SOURCES AND SYNC TIME
        sources_used = []
        if "خطة الإنجاز والمهام" in data:
            sources_used.append("خطة الإنجاز والمهام")
        if "القرارات العالقة" in data:
            sources_used.append("القرارات العالقة")
        if "حالة المشرفين" in data:
            sources_used.append("حالة المشرفين")
        if "تنسيق الأسرة والسيارة" in data:
            sources_used.append("تنسيق الأسرة")

        sync_time = dt.datetime.now().strftime("%H:%M:%S")
        output.append("ℹ️ **المصادر والمزامنة**")
        output.append(f"المصادر: {', '.join(sources_used) if sources_used else 'لا توجد'}")
        output.append(f"آخر مزامنة: {sync_time}")
        output.append(f"وقت التقرير: {started.strftime('%Y-%m-%d %H:%M:%S')}")

        send(chat_id, "\n".join(output))
    except Exception as exc:
        error_msg = str(exc)[:200]
        send(chat_id, f"❌ خطأ في إنشاء البريف: {error_msg}")
        _save_status("COMMAND_BRIEF", "ERROR", exc)


def command_update(chat_id: int, text: str):
    match = re.match(r'^/update\s+"([^"]+)"\s+([A-Za-z]{1,3}[0-9]+)\s+(.+)$', text, re.S)
    if not match:
        send(chat_id, 'الاستخدام: /update "اسم الشيت" B12 القيمة الجديدة')
        return
    tab, a1, value = match.group(1), match.group(2).upper(), match.group(3).strip()
    token = secrets.token_hex(3)
    _PENDING_SHEET_UPDATES[token] = {
        "sheet": tab, "a1": a1, "value": value, "expires": time.time() + 600
    }
    send(
        chat_id,
        f"⚠️ اقتراح تحديث\nالشيت: {tab}\nالخلية: {a1}\nالقيمة: {value}"
        f"\n\nللتنفيذ خلال 10 دقائق: /confirm {token}",
    )


def command_confirm(chat_id: int, token: str):
    item = _PENDING_SHEET_UPDATES.pop(token.strip(), None)
    if not item or item["expires"] < time.time():
        send(chat_id, "❌ رمز التأكيد غير صالح أو انتهت مدته.")
        return
    from connectors.sheet_intelligence import update_cell
    result = update_cell(item["sheet"], item["a1"], item["value"])
    send(
        chat_id,
        f"✅ تم التحديث\n{item['sheet']}!{item['a1']}"
        f"\nالقيمة السابقة: {result.get('before', '')}"
        f"\nالقيمة الجديدة: {result.get('after', item['value'])}",
    )


def _needs_sheet_context(text: str):
    return bool(re.search(
        r"sheet|spreadsheet|شيت|جدول|ناقص|غير مكتمل|متأخر|القادم|pending|"
        r"incomplete|why|لماذا|خطة|أولوية",
        text or "", re.I,
    ))


def command_start(chat_id: int):
    send(
        chat_id,
        "أهلًا عبدالرحمن، وكيلك الشخصي متصل ويستقبل الأسئلة ✅\n\n"
        "يمكنك كتابة أي سؤال مباشرة بالعربية أو الإنجليزية.\n"
        "المدخلات والإجابات تُحفظ في Google Sheets بعد فحص الخصوصية.\n\n"
        "/profile — الملف المهني\n/sources — المصادر\n/selftest — فحص كامل\n"
        "/ai_status — فحص Claude\n/storage_status — فحص الحفظ\n"
        "/sheet — الشيتات المتصلة\n/find كلمة — البحث\n/brief — البريف التنفيذي\n/pending — القادم والناقص والحل\n"
        "/update — اقتراح تحديث\n/help — المساعدة",
    )


def command_profile(chat_id: int):
    send(
        chat_id,
        "👤 عبدالرحمن بكر هوساوي\nرئيس قسم التأهيل وأخصائي علاج طبيعي أول\n"
        "التخصص: التقييم المتقدم للحركة والألم وإعادة التأهيل\n"
        "النظام: Abdulrahman AI OS — Chief of Staff سريري وإداري وتعليمي.",
    )


def _source_summary():
    groups = [("المعرفة", BASE / "knowledge"), ("المهارات", BASE / "skills"),
              ("المحفزات", BASE / "prompts"), ("المواد التعليمية", BASE / "materials"),
              ("الوثائق", BASE / "docs")]
    lines = ["📚 مصادر الوكيل"]
    total = 0
    for label, path in groups:
        count = sum(1 for p in path.rglob("*") if p.is_file() and p.suffix.lower() in
                    {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}) if path.exists() else 0
        total += count
        lines.append(f"• {label}: {count} ملف")
    lines.append(f"\nالإجمالي القابل للفهرسة: {total} ملف")
    return "\n".join(lines)


def command_sources(chat_id: int):
    send(chat_id, _source_summary())


def command_ai_status(chat_id: int):
    if _bedrock_configured():
        send(chat_id, f"🤖 Claude on AWS Bedrock: configured ✅\nRegion: {AWS_REGION}\nModel: {BEDROCK_MODEL_ID}")
    else:
        send(chat_id, "❌ إعداد AWS Bedrock غير مكتمل في Railway Variables.")


def command_storage_status(chat_id: int):
    if not _sheets_configured():
        send(chat_id, "❌ Google Sheets غير مهيأ. أضف GOOGLE_SHEET_ID وGOOGLE_SERVICE_ACCOUNT_JSON.")
        return
    try:
        if GOOGLE_SHEETS_WEBHOOK_URL and GOOGLE_SHEETS_WEBHOOK_SECRET:
            _append(STATUS_TAB, [_now(), "STORAGE_TEST", "OK", "Webhook connected", "v1.2", AWS_REGION, BEDROCK_MODEL_ID, _now()])
        else:
            _sheets().spreadsheets().get(spreadsheetId=GOOGLE_SHEET_ID, fields="spreadsheetId").execute()
        send(chat_id, "💾 Google Sheets: connected ✅\nسيتم حفظ المدخلات والمحادثات والحالة.")
    except Exception as exc:
        send(chat_id, f"❌ تعذر الاتصال بـ Google Sheets: {str(exc)[:220]}")


def _selftest():
    checks = []
    try:
        me = api("getMe", timeout=20)
        checks.append(("Telegram API", True, "@" + str(me.get("username", ""))))
    except Exception as exc:
        checks.append(("Telegram API", False, str(exc)[:120]))
    for name, path in [("Manager", BASE/"engine"/"manager.py"),
                       ("Chief of Staff", BASE/"engine"/"chief_of_staff.py"),
                       ("Store", BASE/"engine"/"store.py"),
                       ("Knowledge", BASE/"knowledge"), ("Skills", BASE/"skills")]:
        checks.append((name, path.exists(), "موجود" if path.exists() else "مفقود"))
    checks.append(("Claude / Bedrock", _bedrock_configured(), "مهيأ" if _bedrock_configured() else "غير مهيأ"))
    checks.append(("Google Sheets", _sheets_configured(), "مهيأ" if _sheets_configured() else "غير مهيأ"))
    try:
        from connectors.aws_transcribe import configured as audio_configured
        audio_ok = audio_configured()
    except Exception:
        audio_ok = False
    checks.append(("Voice / Transcribe", audio_ok, "مهيأ" if audio_ok else "غير مهيأ"))
    checks.append(("Memory / Orchestrator", (BASE/"engine"/"agent_runtime.py").exists(), "موجود"))
    ok = sum(1 for _, passed, _ in checks if passed)
    lines = [f"🩺 Self-test: {ok}/{len(checks)} ناجح"]
    lines.extend(f"{'✅' if passed else '❌'} {name}: {detail}" for name, passed, detail in checks)
    lines.append("\n🔐 الحماية: TELEGRAM_ALLOWED_CHAT_ID مفعّل." if ALLOWED_CHAT_ID
                 else "\n🔐 الحماية: المالك مثبت تلقائيًا.")
    return "\n".join(lines)


def command_selftest(chat_id: int):
    send(chat_id, _selftest())


def _download_telegram_file(file_id: str, suffix=".ogg"):
    import tempfile
    info = api("getFile", {"file_id": file_id}, timeout=30)
    file_path = info.get("file_path")
    if not file_path:
        raise RuntimeError("Telegram did not return a file path")
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    fd, path = tempfile.mkstemp(prefix="telegram-", suffix=suffix)
    os.close(fd)
    urllib.request.urlretrieve(url, path)
    return path


def _transcribe_telegram(file_id: str, kind: str):
    from connectors.aws_transcribe import transcribe_file
    suffix = ".ogg" if kind == "VOICE" else ".mp3"
    path = _download_telegram_file(file_id, suffix=suffix)
    try:
        return transcribe_file(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def handle_message(message: dict):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    if not _authorized(chat_id, chat.get("type", "")):
        send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
        return

    text, kind, attachment = _message_payload(message)
    command = text.split()[0].split("@")[0].lower() if text else ""
    iid = _local_capture(text, message, kind)
    handlers = {
        "/start": command_start, "/help": command_start, "/profile": command_profile,
        "/sources": command_sources, "/selftest": command_selftest,
        "/ai_status": command_ai_status, "/storage_status": command_storage_status,
        "/brief": command_brief, "/b": command_brief,
    }
    handler = handlers.get(command)
    if handler:
        handler(chat_id)
        _save_intake(iid, message, text, kind, attachment, "COMPLETED")
        return
    if command == "/sheet":
        command_sheet(chat_id)
        _save_intake(iid, message, text, kind, attachment, "COMPLETED")
        return
    if command == "/find":
        command_find(chat_id, text[len(command):].strip())
        _save_intake(iid, message, text, kind, attachment, "COMPLETED")
        return
    if command == "/pending":
        command_pending(chat_id)
        _save_intake(iid, message, text, kind, attachment, "COMPLETED")
        return
    if command == "/update":
        command_update(chat_id, text)
        _save_intake(iid, message, text, kind, attachment, "REVIEW_REQUIRED")
        return
    if command == "/confirm":
        command_confirm(chat_id, text[len(command):].strip())
        _save_intake(iid, message, text, kind, attachment, "COMPLETED")
        return
    if command.startswith("/"):
        send(chat_id, "أمر غير معروف. استخدم /help")
        _save_intake(iid, message, text, kind, attachment, "ERROR", error="UNKNOWN_COMMAND")
        return
    if kind in {"VOICE", "AUDIO"}:
        send(chat_id, "🎙️ تم استلام الصوت، جارٍ التفريغ والتحليل...")
        try:
            text = _transcribe_telegram(attachment, kind)
            send(chat_id, "📝 التفريغ:\n" + text[:3000])
        except Exception as exc:
            _save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)
            raise
    elif kind != "TEXT":
        send(chat_id, "✅ تم حفظ بيانات المرفق. تحليل الصور والملفات سيُفعّل في مرحلة مستقلة.")
        _save_intake(iid, message, text, kind, attachment, "RECEIVED")
        return
    if not text:
        return

    cid = f"CV-{chat_id}-{message.get('message_id', '')}"
    try:
        from agent_runtime import remember
        category = _category(text, kind)
        remember(chat_id, "user", text, message.get("message_id", ""), category)
        api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        sheet_context = ""
        if _needs_sheet_context(text):
            try:
                sheet_context = _sheet_context()
            except Exception as exc:
                print(f"Sheet context error: {exc}", flush=True)
        answer, usage, latency, sources = ask_bedrock(
            chat_id, text, sheet_context=sheet_context
        )
        remember(chat_id, "assistant", answer, message.get("message_id", ""), category)
        sheet_ok = _save_conversation(cid, iid, text, answer, usage, latency, "COMPLETED")
        _save_intake(iid, message, text, kind, attachment, "COMPLETED", response_id=cid)
        source_note = ("\n\n📚 المصادر: " + "، ".join(sources[:4])) if sources else ""
        send(chat_id, answer + source_note + ("\n\n💾 تم الحفظ في Google Sheets." if sheet_ok else "\n\n⚠️ تم الرد، لكن حفظ Google Sheets غير متصل."))
    except Exception as exc:
        _save_conversation(cid, iid, text, "", {}, 0, "ERROR", error=exc)
        _save_intake(iid, message, text, kind, attachment, "ERROR", response_id=cid, error=exc)
        _save_status("TELEGRAM_AI_PIPELINE", "ERROR", exc)
        raise


def configure_commands():
    commands = json.dumps([
        {"command":"start","description":"تشغيل الوكيل"},
        {"command":"profile","description":"عرض الملف المهني"},
        {"command":"sources","description":"عرض مصادر المعرفة"},
        {"command":"selftest","description":"فحص المكونات"},
        {"command":"ai_status","description":"فحص Claude على AWS"},
        {"command":"storage_status","description":"فحص حفظ Google Sheets"},
        {"command":"sheet","description":"عرض الشيتات المتصلة"},
        {"command":"find","description":"البحث في الشيت"},
        {"command":"brief","description":"البريف التنفيذي للعبدالرحمن"},
        {"command":"pending","description":"القادم والناقص والحل"},
        {"command":"update","description":"اقتراح تحديث خلية"},
        {"command":"confirm","description":"تأكيد التحديث"},
        {"command":"help","description":"المساعدة"},
    ], ensure_ascii=False)
    api("setMyCommands", {"commands": commands})


def run():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    me = api("getMe", timeout=20)
    configure_commands()
    print(f"Telegram polling enabled for @{me.get('username')}", flush=True)
    _save_status("TELEGRAM_BOT", "OK", f"Polling started for @{me.get('username')}")
    offset = 0
    while True:
        try:
            updates = api("getUpdates", {"timeout":45, "offset":offset,
                          "allowed_updates":json.dumps(["message"])}, timeout=55)
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                if update.get("message"):
                    try:
                        handle_message(update["message"])
                    except Exception as exc:
                        chat_id = (update["message"].get("chat") or {}).get("id")
                        if chat_id is not None:
                            send(chat_id, f"❌ تعذر تنفيذ الطلب: {str(exc)[:220]}")
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(f"Telegram polling error: {exc}", flush=True)
            _save_status("TELEGRAM_POLLING", "ERROR", exc)
            time.sleep(5)


if __name__ == "__main__":
    run()

# -*- coding: utf-8 -*-
"""Read-only, governed retrieval from the ConvCS clinical knowledge workbook.

This source contains mixed clinical, coaching, and psychosomatic material. It is
therefore evidence for clinician reflection only: it never becomes personal
memory, a diagnosis, a proven causal explanation, or an autonomous treatment
instruction.
"""
from __future__ import annotations

import json
import os
import re

from . import google_credentials


DEFAULT_SHEET_ID = "1vRBGlkjGuO1xPFbQs6HRXRdrhdTuttkijmfFKfR720s"
SHEET_ID = os.environ.get("CLINICAL_KNOWLEDGE_SHEET_ID", DEFAULT_SHEET_ID).strip()
MAX_ROWS = max(20, min(int(os.environ.get("CLINICAL_KNOWLEDGE_MAX_ROWS", "250")), 500))
_SERVICE = None

TAB_SPECS = {
    "Chronic_Disease_Somatic_Map": {
        "gid": 0,
        "columns": 8,
        "headers": ("رمز المرض", "المشكلة الصحية / المرض المزمن"),
        "use": "MIXED_CLINICAL_HYPOTHESIS",
        "guardrail": "Physiological statements require independent clinical corroboration; emotional material is not disease causation.",
    },
    "Meditation_Protocols": {
        "gid": 1001,
        "columns": 3,
        "headers": ("رمز البروتوكول", "المشكلة", "الخطوات"),
        "use": "SUPPORTIVE_PRACTICE_ONLY",
        "guardrail": "Optional supportive practice only; never replace assessment, urgent care, medication, or indicated treatment.",
    },
    "Clinical_Guidance_Engine": {
        "gid": 1002,
        "columns": 4,
        "headers": ("رمز التوجيه", "عبارة المريض", "إعادة التأطير للمعالج", "العبارة الموجهة"),
        "use": "CLINICIAN_COMMUNICATION_DRAFT",
        "guardrail": "Draft communication language requiring clinician review and patient-centred adaptation.",
    },
    "Keyword_Phrases_Bank": {
        "gid": 1003,
        "columns": 3,
        "headers": ("المفهوم", "سريرياً", "محتوى"),
        "use": "EDUCATIONAL_LANGUAGE_DRAFT",
        "guardrail": "Educational wording only; avoid certainty, blame, or unsupported causal claims.",
    },
    "Symptoms_Psychological_Roots": {
        "gid": 1004,
        "columns": 6,
        "headers": ("رمز الحالة", "العارض الجسدي / المرض", "الجذر الشعوري والرسالة النفسية"),
        "use": "REFLECTION_ONLY_NOT_ETIOLOGY",
        "guardrail": "Psychological-root statements are reflection hypotheses only, never a diagnosis, medical fact, or proven cause of disease.",
    },
}

_PRIVATE_IDENTIFIER_RE = re.compile(
    r"(?i)(mrn|medical\s*record|رقم\s*الملف|رقم\s*الهوية|هوية\s*المريض)\s*[:#-]?\s*[A-Z0-9-]+"
)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)")
_WORD_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_STOP_WORDS = {
    "المريض", "المريضة", "حالة", "الحالة", "عندي", "لدي", "ما", "هو", "هي",
    "the", "a", "an", "patient", "case", "with", "and", "or", "for",
}


def configured() -> bool:
    return bool(SHEET_ID and google_credentials.service_account_info())


def contains_private_identifier(text: str) -> bool:
    value = str(text or "")
    return bool(_PRIVATE_IDENTIFIER_RE.search(value) or _EMAIL_RE.search(value) or _PHONE_RE.search(value))


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    info = google_credentials.service_account_info()
    if not info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured or invalid")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    _SERVICE = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _SERVICE


def metadata() -> list[dict]:
    if not SHEET_ID:
        raise RuntimeError("CLINICAL_KNOWLEDGE_SHEET_ID is empty")
    result = _service().spreadsheets().get(
        spreadsheetId=SHEET_ID, fields="properties(title),sheets.properties"
    ).execute()
    return [
        {
            "title": item["properties"]["title"],
            "sheetId": item["properties"]["sheetId"],
            "rows": item["properties"].get("gridProperties", {}).get("rowCount", 0),
            "columns": item["properties"].get("gridProperties", {}).get("columnCount", 0),
        }
        for item in result.get("sheets", [])
    ]


def _column_letter(number: int) -> str:
    out = ""
    value = max(1, int(number))
    while value:
        value, remainder = divmod(value - 1, 26)
        out = chr(65 + remainder) + out
    return out


def _rows(tab: str) -> list[list]:
    spec = TAB_SPECS[tab]
    safe_tab = tab.replace("'", "''")
    end_col = _column_letter(spec["columns"])
    result = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{safe_tab}'!A1:{end_col}{MAX_ROWS}",
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return []
    actual = tuple(str(value).strip() for value in rows[0])
    missing = [header for header in spec["headers"] if header not in actual]
    if missing:
        raise RuntimeError(f"Clinical sheet schema mismatch in {tab}: missing {', '.join(missing)}")
    return rows


def _tokens(query: str) -> list[str]:
    words = [word.lower() for word in _WORD_RE.findall(query or "")]
    return [word for word in words if len(word) >= 2 and word not in _STOP_WORDS][:16]


def search(query: str, max_results: int = 8) -> list[dict]:
    value = str(query or "").strip()
    if not value:
        raise ValueError("اكتب العرض أو المفهوم السريري المطلوب البحث عنه.")
    if contains_private_identifier(value):
        raise ValueError("أزل رقم الملف/الهوية والهاتف والبريد قبل البحث في المرجع السريري.")
    tokens = _tokens(value)
    if not tokens:
        raise ValueError("لم أجد كلمات سريرية كافية للبحث.")

    lowered_query = value.lower()
    matches = []
    for tab, spec in TAB_SPECS.items():
        rows = _rows(tab)
        if len(rows) < 2:
            continue
        headers = rows[0]
        for row_number, row in enumerate(rows[1:], 2):
            text = " | ".join(str(cell) for cell in row).lower()
            token_hits = sum(1 for token in tokens if token in text)
            exact_bonus = 4 if lowered_query in text else 0
            if not token_hits and not exact_bonus:
                continue
            title_index = 1 if tab != "Keyword_Phrases_Bank" else 0
            matches.append({
                "score": exact_bonus + token_hits,
                "source_class": "CLINICAL_KNOWLEDGE",
                "tab": tab,
                "row": row_number,
                "code": str(row[0]) if row else "",
                "title": str(row[title_index]) if len(row) > title_index else "",
                "headers": headers[: spec["columns"]],
                "values": row[: spec["columns"]],
                "use": spec["use"],
                "guardrail": spec["guardrail"],
                "source_ref": (
                    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={spec['gid']}"
                ),
            })
    matches.sort(key=lambda item: (-item["score"], item["tab"], item["row"]))
    return matches[: max(1, min(int(max_results), 20))]


def compact_context(query: str, max_results: int = 6, limit: int = 12000) -> str:
    results = search(query, max_results=max_results)
    if not results:
        return ""
    bundle = {
        "source": "ConvCS_Clinical_Master_Engine",
        "source_class": "CLINICAL_KNOWLEDGE",
        "mode": "READ_ONLY_SPECIALIST_REVIEW_REQUIRED",
        "mandatory_rules": [
            "Start with red flags and conventional clinical assessment.",
            "Treat all psychological-root content as reflection-only, not diagnosis or proven etiology.",
            "Do not imply that emotions caused cancer, infection, obesity, or another disease.",
            "Meditation and reframing are optional supportive tools, never replacements for indicated care.",
            "Use hypothesis, needs-confirmation, and test-retest language; final judgment belongs to the clinician.",
        ],
        "results": results,
    }
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    return "GOVERNED CLINICAL SHEET EVIDENCE:\n" + payload[: max(1000, int(limit))]


def status() -> dict:
    result = {
        "configured": configured(),
        "sheet_id_present": bool(SHEET_ID),
        "expected_tabs": len(TAB_SPECS),
        "ready": False,
        "tabs_found": 0,
        "missing_tabs": list(TAB_SPECS),
    }
    if not result["configured"]:
        return result
    try:
        rows = metadata()
        titles = {row["title"] for row in rows}
        result["tabs_found"] = len(titles & set(TAB_SPECS))
        result["missing_tabs"] = sorted(set(TAB_SPECS) - titles)
        result["ready"] = not result["missing_tabs"]
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:180]
    return result


def status_text() -> str:
    item = status()
    lines = [
        "🩺 Clinical Knowledge Sheet",
        f"Configured: {'YES ✅' if item['configured'] else 'NO'}",
        f"Expected tabs: {item['expected_tabs']}",
        f"Tabs found: {item['tabs_found']}",
        f"Ready: {'YES ✅' if item['ready'] else 'NO'}",
        "Mode: read-only + specialist review required",
    ]
    if item.get("missing_tabs"):
        lines.append("Missing tabs: " + ", ".join(item["missing_tabs"]))
    if item.get("error"):
        lines.append("Safe error: " + item["error"])
    return "\n".join(lines)


# -*- coding: utf-8 -*-
"""WO-8: conservative multi-intent extraction and linked operational recording.

This module is deliberately deterministic and fail-closed. It does not execute
Calendar writes, send messages, or invent missing owners/dates/dependencies.
One intake may produce multiple typed records that share an intake_id and
relation_group_id. Explicit dependencies are recorded as CONFIRMED; otherwise a
same-intake decision/waiting relationship is only a POSSIBLE_DEPENDENCY with
NEEDS_INPUT status.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass

from store import Store

NEEDS_INPUT = "NEEDS_INPUT"

_CLINICAL_RE = re.compile(
    r"patient|مريض|mrn|medical\s*record|رقم\s*الملف|رقم\s*الهوية|diagnosis|تشخيص|"
    r"clinical|سريري|pain|ألم|علاج|دواء|عملية|surgery|symptom|عرض\s*مرضي",
    re.I,
)
_DECISION_RE = re.compile(
    r"لازم\s+أقرر|لازم\s+نقرر|\bأقرر\b|\bنقرر\b|\bقرار\b|\bdecid(?:e|ing)\b|"
    r"\bdecision\b|\bchoose\b|\bاختار\b|هل\s+.+?\s+أو\s+.+",
    re.I,
)
_WAITING_RE = re.compile(
    r"أنتظر|انتظر|بانتظار|ننتظر|معل[قّ]|pending|waiting|awaiting|"
    r"رد\s+.+?موافقة|موافقة\s+.+?(?:معلقة|منتظرة|pending)",
    re.I,
)
_TASK_RE = re.compile(
    r"\btask\b|\btodo\b|\bmust\b|مطلوب|يجب|استكمال|أكمل|اكمل|جهز|جهّز|"
    r"إعداد|اعداد|أرسل|ارسل|نفذ|نفّذ|اعمل|لازم\s+(?!أقرر|نقرر)",
    re.I,
)
_IDEA_RE = re.compile(r"\bidea\b|\bsuggest(?:ion)?\b|فكرة|اقتراح", re.I)
_DATE_RE = re.compile(
    r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b|"
    r"اليوم|غد[ًاا]?|بكره|بكرة|بعد\s+(?:غد|بكره)|"
    r"الاثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة|الجمعه|السبت|الأحد|الاحد|"
    r"today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday",
    re.I,
)
_TIME_RE = re.compile(
    r"(?:الساعه|الساعة|عند|at)\s*[٠-٩0-9]{1,2}(?::[٠-٩0-9]{2})?\s*"
    r"(?:صباحا|صباحًا|صباح|ص|am|مساء|مساءً|م|pm)?|"
    r"\b[٠-٩0-9]{1,2}:[٠-٩0-9]{2}\s*(?:صباحا|صباحًا|صباح|ص|am|مساء|مساءً|م|pm)?",
    re.I,
)
_EXPLICIT_DEP_RE = re.compile(
    r"مشروط(?:ة)?\s+ب(?:هذه\s+|تلك\s+)?الموافقة|يعتمد(?:\s+\w+){0,5}\s+على\s+(?:هذه\s+|تلك\s+)?الموافقة|"
    r"بعد\s+(?:الحصول\s+على\s+)?الموافقة|لا\s+(?:يمكن|نستطيع)\s+.+?بدون\s+الموافقة|"
    r"depends\s+on\s+(?:the\s+)?approval|conditional\s+on\s+(?:the\s+)?approval|requires?\s+approval",
    re.I,
)

# Split only at strong boundaries; Arabic conjunctions are preserved unless they
# clearly introduce another managerial clause.
_SPLIT_RE = re.compile(
    r"(?:[.!?؟؛;\n]+|،|,(?!\d)|\s+(?=(?:وأنتظر|وانتظر|بانتظار|ومطلوب|مطلوب|"
    r"وعندي|ولدي|والاثنين|والثلاثاء|والأربعاء|والاربعاء|والخميس|والجمعة|والسبت|والأحد|والاحد)\b))",
    re.I,
)


@dataclass(frozen=True)
class Intent:
    kind: str
    evidence: str
    ordinal: int


def _clean(text: str, limit: int = 280) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" -،,.;؛")[:limit]


def _clauses(text: str) -> list[str]:
    rows = [_clean(x) for x in _SPLIT_RE.split(text or "")]
    return [x for x in rows if x]


def _append_unique(rows: list[Intent], kind: str, evidence: str) -> None:
    evidence = _clean(evidence)
    if not evidence:
        return
    key = (kind, evidence.casefold())
    if any((x.kind, x.evidence.casefold()) == key for x in rows):
        return
    rows.append(Intent(kind=kind, evidence=evidence, ordinal=len(rows) + 1))


def extract_intents(text: str, kind: str = "TEXT") -> list[Intent]:
    """Return all confidently recognizable intents; never infer missing fields."""
    value = _clean(text, 8000)
    if not value or value.startswith("[VOICE_PENDING_") or value.startswith("[AUDIO_PENDING_"):
        return []
    if _CLINICAL_RE.search(value):
        return [Intent("CLINICAL_PRIVATE", "[CLINICAL_PRIVATE_REDACTED_AT_SOURCE]", 1)]

    rows: list[Intent] = []
    clauses = _clauses(value) or [value]
    for clause in clauses:
        is_decision = bool(_DECISION_RE.search(clause))
        if is_decision:
            _append_unique(rows, "DECISION", clause)
        if _WAITING_RE.search(clause):
            _append_unique(rows, "WAITING_FOR", clause)
        # "لازم أقرر" is a decision signal, not a second TASK merely because it
        # contains "لازم".
        if _TASK_RE.search(clause) and not (is_decision and re.search(r"لازم\s+(?:أقرر|نقرر)", clause)):
            _append_unique(rows, "TASK", clause)
        if _IDEA_RE.search(clause):
            _append_unique(rows, "IDEA", clause)
        if _DATE_RE.search(clause) and _TIME_RE.search(clause):
            _append_unique(rows, "APPOINTMENT_CANDIDATE", clause)

    # If a temporal phrase spans one punctuation boundary, keep it as one candidate
    # only when the date and clock are near each other. We store raw evidence; the
    # guarded Calendar parser remains the only component allowed to resolve it.
    if not any(x.kind == "APPOINTMENT_CANDIDATE" for x in rows):
        date_match = _DATE_RE.search(value)
        time_match = _TIME_RE.search(value)
        if date_match and time_match and abs(date_match.start() - time_match.start()) <= 140:
            start = max(0, min(date_match.start(), time_match.start()) - 60)
            end = min(len(value), max(date_match.end(), time_match.end()) + 80)
            _append_unique(rows, "APPOINTMENT_CANDIDATE", value[start:end])
    return rows


def _record_id(iid: str, intent: Intent) -> str:
    raw = f"{iid}|{intent.kind}|{intent.ordinal}|{intent.evidence}".encode("utf-8")
    return "REC-" + hashlib.sha256(raw).hexdigest()[:12].upper()


def _base_record(iid: str, group_id: str, intent: Intent, source: str, source_ref: str) -> dict:
    return {
        "record_id": _record_id(iid, intent),
        "intake_id": iid,
        "relation_group_id": group_id,
        "record_type": intent.kind,
        "source": source,
        "source_ref": source_ref,
        "evidence": intent.evidence,
        "captured_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def _typed_record(iid: str, group_id: str, intent: Intent, source: str, source_ref: str) -> tuple[str, dict] | None:
    base = _base_record(iid, group_id, intent, source, source_ref)
    if intent.kind == "TASK":
        base.update({
            "العنوان": intent.evidence,
            "الحالة": "لم تبدأ",
            "owner": NEEDS_INPUT,
            "due_date": NEEDS_INPUT,
            "next_step": NEEDS_INPUT,
            "approval_required": NEEDS_INPUT,
        })
        return "tasks", base
    if intent.kind == "WAITING_FOR":
        base.update({
            "item": intent.evidence,
            "status": "WAITING",
            "expected_from": NEEDS_INPUT,
            "expected_by": NEEDS_INPUT,
            "follow_up_date": NEEDS_INPUT,
            "next_action": NEEDS_INPUT,
        })
        return "waiting_for", base
    if intent.kind == "DECISION":
        base.update({
            "القرار": intent.evidence,
            "الحالة": "بانتظار الحسم",
            "owner": NEEDS_INPUT,
            "decision_criterion": NEEDS_INPUT,
            "review_date": NEEDS_INPUT,
        })
        return "decisions", base
    if intent.kind == "APPOINTMENT_CANDIDATE":
        base.update({
            "action_id": base["record_id"],
            "type": "APPOINTMENT_CANDIDATE",
            "status": "NEEDS_CONFIRMATION",
            "raw_temporal_text": intent.evidence,
            "resolved_start": NEEDS_INPUT,
            "external_effect": "GOOGLE_CALENDAR_CREATE",
            "approval_required": True,
        })
        return "action_queue", base
    return None


def _relation_id(group_id: str, source_id: str, target_id: str, relation: str) -> str:
    raw = f"{group_id}|{source_id}|{target_id}|{relation}".encode("utf-8")
    return "REL-" + hashlib.sha256(raw).hexdigest()[:12].upper()


def record_intents(
    iid: str,
    text: str,
    *,
    kind: str = "TEXT",
    source: str = "TELEGRAM",
    source_ref: str = "",
    store: Store | None = None,
) -> dict:
    """Atomically attach all recognized intents and linked records to one intake."""
    intents = extract_intents(text, kind)
    store = store or Store()
    group_id = "RG-" + hashlib.sha256(str(iid).encode("utf-8")).hexdigest()[:12].upper()

    def mutate(state):
        inbox = state.setdefault("unified_inbox", [])
        item = next((row for row in inbox if row.get("id") == iid), None)
        if item is None:
            raise ValueError(f"inbox item not found: {iid}")

        # A voice placeholder may be captured before transcription. Replace it only
        # with non-clinical transcript text; clinical text stays minimized.
        if intents and intents[0].kind == "CLINICAL_PRIVATE":
            item["content"] = "[REDACTED_FROM_PERSONAL_OS]"
            item["sensitive"] = True
        elif text and not str(text).startswith("["):
            item["content"] = _clean(text, 8000)

        linked_ids: list[str] = []
        classifications: list[str] = []
        records_by_type: dict[str, list[str]] = {}
        changed = False

        for intent in intents:
            classifications.append(intent.kind)
            typed = _typed_record(iid, group_id, intent, source, source_ref)
            if typed is None:
                continue
            section, record = typed
            rows = state.setdefault(section, [])
            rid = record["record_id"]
            if not any(row.get("record_id") == rid for row in rows):
                rows.append(record)
                changed = True
            linked_ids.append(rid)
            records_by_type.setdefault(intent.kind, []).append(rid)

        links = state.setdefault("record_links", [])
        decisions = records_by_type.get("DECISION", [])
        waits = records_by_type.get("WAITING_FOR", [])
        if decisions and waits:
            explicit = bool(_EXPLICIT_DEP_RE.search(text or ""))
            relation = "BLOCKED_BY" if explicit else "POSSIBLE_DEPENDENCY"
            status = "CONFIRMED" if explicit else NEEDS_INPUT
            for decision_id in decisions:
                for waiting_id in waits:
                    link = {
                        "relation_id": _relation_id(group_id, decision_id, waiting_id, relation),
                        "intake_id": iid,
                        "relation_group_id": group_id,
                        "source_record_id": decision_id,
                        "target_record_id": waiting_id,
                        "relation": relation,
                        "status": status,
                        "basis": (
                            "explicit dependency language in the same intake"
                            if explicit else
                            "same intake contains both decision and waiting; dependency is not explicit"
                        ),
                    }
                    if not any(row.get("relation_id") == link["relation_id"] for row in links):
                        links.append(link)
                        changed = True

        new_classes = list(dict.fromkeys(classifications))
        before = (item.get("classifications"), item.get("linked_record_ids"), item.get("relation_group_id"), item.get("status"))
        item["classifications"] = new_classes
        item["classification"] = (
            "MULTI" if len(new_classes) > 1 else (new_classes[0] if new_classes else None)
        )
        item["linked_record_ids"] = list(dict.fromkeys(linked_ids))
        item["relation_group_id"] = group_id
        item["status"] = "RECORDED" if new_classes else item.get("status", "NEW")
        item["classified_at"] = dt.datetime.now().isoformat(timespec="seconds") if new_classes else item.get("classified_at")
        after = (item.get("classifications"), item.get("linked_record_ids"), item.get("relation_group_id"), item.get("status"))
        changed = changed or before != after

        return changed, {
            "intake_id": iid,
            "relation_group_id": group_id,
            "classifications": new_classes,
            "linked_record_ids": list(dict.fromkeys(linked_ids)),
            "record_count": len(set(linked_ids)),
        }

    return store.transaction(mutate, "wo8_multi_intent_record", intake_id=iid)

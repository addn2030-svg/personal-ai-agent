# -*- coding: utf-8 -*-
"""Multi-model advisory council for high-value non-clinical decisions.

Claude, GPT and Gemini review the same question independently through OpenRouter.
A judge then synthesizes consensus, disagreements and a recommendation. Results are
provenance-labelled and stored as advisory evidence; the council never executes an
action or writes Calendar/project/task state directly.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
from typing import Any

from connectors import model_gateway
from engine.store import Store, log_event

MAX_QUESTION_CHARS = int(os.environ.get("AI_COUNCIL_MAX_QUESTION_CHARS", "5000"))
MAX_CONTEXT_CHARS = int(os.environ.get("AI_COUNCIL_MAX_CONTEXT_CHARS", "12000"))
ADVISER_MAX_TOKENS = int(os.environ.get("AI_COUNCIL_ADVISER_MAX_TOKENS", "700"))
JUDGE_MAX_TOKENS = int(os.environ.get("AI_COUNCIL_JUDGE_MAX_TOKENS", "900"))
AI_COUNCIL_JUDGE_MODEL = os.environ.get("AI_COUNCIL_JUDGE_MODEL", "").strip()

ROLE_INSTRUCTIONS = {
    "manager": (
        "You are the operations/management adviser. Evaluate the decision, dependencies, "
        "execution risk, reversibility and owner impact. Give concise evidence-based advice."
    ),
    "critic": (
        "You are the independent critical reviewer. Challenge assumptions, identify failure "
        "modes, missing evidence and safer alternatives. Give concise evidence-based advice."
    ),
    "google": (
        "You are the research/integration adviser. Focus on information gaps, external-system "
        "dependencies, interoperability and verification steps. Give concise evidence-based advice."
    ),
}


def enabled() -> bool:
    return os.environ.get("AI_COUNCIL_ENABLED", "1").strip() != "0" and model_gateway.configured()


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _council_id(question: str, stamp: str) -> str:
    digest = hashlib.sha256((stamp + "|" + question).encode("utf-8")).hexdigest()[:10].upper()
    return "COUNCIL-" + digest


def _adviser_messages(role: str, question: str, context: str) -> list[dict]:
    system = (
        ROLE_INSTRUCTIONS[role]
        + "\nDo not claim access to systems not present in the supplied evidence. "
        + "Do not reveal hidden chain-of-thought. Return only conclusions, evidence, risks and next checks."
    )
    user = f"QUESTION:\n{question}"
    if context:
        user += f"\n\nCONTEXT / EVIDENCE:\n{context}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_json_object(text: str) -> dict:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def _judge_messages(question: str, panel: list[dict]) -> list[dict]:
    compact_panel = [
        {
            "role": row["role"],
            "model": row["model"],
            "answer": row["answer"][:5000],
        }
        for row in panel
    ]
    system = (
        "You are the final judge for a multi-model advisory council. Synthesize evidence; do not "
        "vote mechanically. Distinguish consensus from disagreement and do not invent facts. "
        "Return one JSON object only with keys: consensus (array of strings), disagreements "
        "(array of strings), blind_spots (array of strings), recommendation (string), "
        "confidence (number 0..1), material_conflict (boolean), requires_owner_decision (boolean), "
        "next_checks (array of strings). Do not include hidden reasoning."
    )
    user = json.dumps(
        {"question": question, "panel": compact_panel},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize_synthesis(raw: dict) -> dict:
    def arr(name):
        value = raw.get(name) or []
        if not isinstance(value, list):
            value = [value]
        return [_clean(x, 1000) for x in value[:10] if _clean(x, 1000)]

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    return {
        "consensus": arr("consensus"),
        "disagreements": arr("disagreements"),
        "blind_spots": arr("blind_spots"),
        "recommendation": _clean(raw.get("recommendation"), 3000),
        "confidence": confidence,
        "material_conflict": bool(raw.get("material_conflict", False)),
        "requires_owner_decision": bool(raw.get("requires_owner_decision", False)),
        "next_checks": arr("next_checks"),
    }


def _persist(record: dict):
    def mutate(S):
        snapshots = S.setdefault("trust_snapshots", [])
        if any(x.get("id") == record["id"] for x in snapshots):
            return False, record["id"]
        snapshots.append(record)

        synthesis = record.get("synthesis") or {}
        if synthesis.get("material_conflict"):
            contradictions = S.setdefault("contradictions", [])
            contradictions.append({
                "id": "CON-" + record["id"].split("-", 1)[-1],
                "created_at": record["created_at"],
                "status": "OPEN",
                "subject": record["question"][:500],
                "project": record.get("project", ""),
                "sources": [x.get("model") for x in record.get("participants", [])],
                "details": synthesis.get("disagreements", []),
                "recommendation": synthesis.get("recommendation", ""),
                "origin": record["id"],
            })
        return True, record["id"]

    return Store().transaction(mutate, "ai_council_saved", council_id=record["id"])


def consult(question: str, *, context: str = "", project: str = "",
            sensitive: bool = False, persist: bool = True) -> dict:
    """Run three independent advisers and one synthesis call.

    Sensitive/clinical content is deliberately rejected here. Clinical reasoning keeps
    the existing protected provider path and should not be fanned out across vendors.
    """
    question = _clean(question, MAX_QUESTION_CHARS)
    context = _clean(context, MAX_CONTEXT_CHARS)
    project = _clean(project, 300)
    if not question:
        raise ValueError("question is required")
    if sensitive:
        raise ValueError("AI Council is disabled for sensitive/clinical content")
    if not enabled():
        raise RuntimeError("AI Council requires OPENROUTER_API_KEY and AI_COUNCIL_ENABLED=1")

    models = model_gateway.models_for_roles()

    def call_one(role: str) -> dict:
        model = models[role]
        answer, usage, latency = model_gateway.openrouter_chat(
            model=model,
            messages=_adviser_messages(role, question, context),
            sensitive=False,
            max_tokens=ADVISER_MAX_TOKENS,
            temperature=0.2,
        )
        return {
            "role": role,
            "model": model,
            "answer": answer,
            "usage": usage,
            "latency_ms": latency,
            "status": "OK",
        }

    panel: list[dict] = []
    failures: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai-council") as executor:
        futures = {executor.submit(call_one, role): role for role in ("manager", "critic", "google")}
        for future in concurrent.futures.as_completed(futures):
            role = futures[future]
            try:
                panel.append(future.result())
            except Exception as exc:  # noqa: BLE001 - independent adviser boundary
                failures.append({"role": role, "model": models[role], "error": str(exc)[:500]})

    panel.sort(key=lambda x: ("manager", "critic", "google").index(x["role"]))
    if len(panel) < 2:
        raise RuntimeError("AI Council needs at least two successful independent advisers")

    judge_model = AI_COUNCIL_JUDGE_MODEL or models["manager"]
    judge_text, judge_usage, judge_latency = model_gateway.openrouter_chat(
        model=judge_model,
        messages=_judge_messages(question, panel),
        sensitive=False,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    parsed = _parse_json_object(judge_text)
    if not parsed:
        parsed = {
            "recommendation": judge_text,
            "confidence": 0.5,
            "material_conflict": bool(failures),
            "requires_owner_decision": True,
            "blind_spots": ["Judge response was not machine-readable JSON"],
        }
    synthesis = _normalize_synthesis(parsed)

    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    record = {
        "kind": "AI_COUNCIL",
        "id": _council_id(question, stamp),
        "created_at": stamp,
        "project": project,
        "question": question,
        "participants": panel,
        "failures": failures,
        "judge": {"model": judge_model, "usage": judge_usage, "latency_ms": judge_latency},
        "synthesis": synthesis,
        "status": "OWNER_DECISION_REQUIRED" if synthesis["requires_owner_decision"] else "ADVISORY",
    }
    if persist:
        _persist(record)
    log_event(
        "AI_COUNCIL_COMPLETED",
        council_id=record["id"],
        participants=len(panel),
        failures=len(failures),
        material_conflict=synthesis["material_conflict"],
    )
    return record


def format_for_telegram(record: dict, max_chars: int = 3500) -> str:
    s = record.get("synthesis") or {}
    lines = [
        f"🧠 AI Council — {record.get('id', '')}",
        "Models: " + ", ".join(x.get("model", "") for x in record.get("participants", [])),
        "",
    ]
    if s.get("consensus"):
        lines.append("✅ الاتفاق")
        lines.extend("• " + x for x in s["consensus"][:4])
    if s.get("disagreements"):
        lines.append("\n⚠️ الاختلافات")
        lines.extend("• " + x for x in s["disagreements"][:4])
    if s.get("recommendation"):
        lines.append("\n🎯 توصية المدير")
        lines.append(s["recommendation"])
    if s.get("next_checks"):
        lines.append("\n🔎 التحقق التالي")
        lines.extend("• " + x for x in s["next_checks"][:4])
    lines.append(f"\nالثقة: {int(float(s.get('confidence', 0)) * 100)}%")
    if s.get("requires_owner_decision"):
        lines.append("👤 يحتاج قرار المالك")
    return "\n".join(lines)[:max_chars]

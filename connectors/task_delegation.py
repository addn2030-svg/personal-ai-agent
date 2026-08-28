# -*- coding: utf-8 -*-
"""Multi-agent delegation and shared-mission orchestration for the Telegram manager.

Models provide reasoning only. This module does not grant browser, Drive, Calendar,
Sheets, email, or outbound-message permissions. External actions remain behind
their existing connectors and approval gates.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from connectors import model_gateway as models

AGENT_ALIASES = {
    "auto": "auto", "claude": "claude", "manager": "claude", "مدير": "claude",
    "gpt": "gpt", "critic": "gpt", "ناقد": "gpt",
    "gemini": "gemini", "research": "gemini", "باحث": "gemini",
}

ROLE_MODELS = {
    "claude": lambda: models.AI_MANAGER_MODEL,
    "gpt": lambda: models.AI_CRITIC_MODEL,
    "gemini": lambda: models.AI_GOOGLE_MODEL,
}

ROLE_LABELS = {
    "claude": "Claude — Manager",
    "gpt": "GPT — Critic",
    "gemini": "Gemini — Researcher",
}

_RESEARCH_RE = re.compile(
    r"research|search|find|discover|trend|scan|instagram|social|sources|latest|"
    r"ابحث|بحث|اكتشف|استكشف|ترند|انستغرام|إنستغرام|منصة|مصادر|الأحدث|احدث", re.I,
)
_CRITIC_RE = re.compile(
    r"review|critic|verify|validate|risk|audit|compare|contract|weakness|"
    r"راجع|دقق|تحقق|مخاطر|تدقيق|قارن|عقد|ثغرات|نقد", re.I,
)
_PRIVATE_RE = re.compile(
    r"\bmrn\b|medical\s*record|رقم\s*الملف|رقم\s*الهوية|هوية\s*المريض|"
    r"patient\s*(name|id)|اسم\s*المريض|\b05\d{8}\b|\+9665\d{8}", re.I,
)


@dataclass
class AgentResult:
    requested: str
    executed_by: str
    provider: str
    model: str
    answer: str
    fallback: bool = False


def contains_private_data(text: str) -> bool:
    return bool(_PRIVATE_RE.search(text or ""))


def choose_agent(task: str) -> str:
    if _RESEARCH_RE.search(task or ""):
        return "gemini"
    if _CRITIC_RE.search(task or ""):
        return "gpt"
    return "claude"


def parse_delegate(value: str) -> tuple[str, str]:
    text = (value or "").strip()
    if not text:
        return "auto", ""
    first, *rest = text.split(maxsplit=1)
    alias = AGENT_ALIASES.get(first.lower())
    if alias:
        return alias, (rest[0].strip() if rest else "")
    return "auto", text


def _system_for(agent: str) -> str:
    common = (
        "You are one adviser inside Abdulrahman AI OS. Work only from the task and "
        "evidence supplied to you. Do not claim you browsed the web, Instagram, Google "
        "Drive, or any external service unless evidence from that connector is included. "
        "Separate facts, assumptions, and recommendations. Be concise and practical. "
        "Never perform or claim an external action; propose it for the manager instead."
    )
    if agent == "gemini":
        return common + " Focus on research framing, discovery angles, alternatives, source gaps, and what evidence should be collected."
    if agent == "gpt":
        return common + " Focus on verification, weaknesses, contradictions, risks, and decision quality."
    return common + " Focus on synthesis, priorities, decisions, delegation, and next actions."


def _openrouter_agent(agent: str, task: str, *, max_tokens: int = 900,
                      temperature: float = 0.2, response_format: dict | None = None) -> AgentResult:
    model = ROLE_MODELS[agent]()
    answer, _usage, _latency = models.openrouter_chat(
        model=model,
        messages=[
            {"role": "system", "content": _system_for(agent)},
            {"role": "user", "content": task},
        ],
        sensitive=False,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    return AgentResult(agent, agent, "openrouter", models.last_route().get("model") or model, answer)


def _bedrock_manager(chat_id: int, task: str, bedrock_fallback, *, requested: str,
                     fallback: bool) -> AgentResult:
    if bedrock_fallback is None:
        raise RuntimeError("Bedrock manager fallback is unavailable")
    prompt = (
        "Delegated manager task. Execute as the protected Claude/Bedrock manager. "
        "Do not claim external browsing or tool access unless evidence is included. "
        "Do not perform external actions; identify any action that needs user approval.\n\n" + task
    )
    answer, _usage, _latency, _sources = bedrock_fallback(chat_id, prompt, sheet_context="")
    return AgentResult(requested, "claude", "bedrock", models.BEDROCK_MODEL_ID, answer, fallback=fallback)


def delegate(chat_id: int, value: str, *, bedrock_fallback=None) -> AgentResult:
    requested, task = parse_delegate(value)
    if not task:
        raise ValueError("اكتب المهمة بعد /delegate")
    if contains_private_data(task):
        if requested in {"gpt", "gemini"}:
            raise ValueError("المهمة تحتوي بيانات خاصة؛ لا يمكن إرسالها إلى وكيل خارجي. استخدم Claude/Bedrock أو أزل المعرّفات.")
        return _bedrock_manager(chat_id, task, bedrock_fallback, requested=requested, fallback=False)
    selected = choose_agent(task) if requested == "auto" else requested
    if selected not in ROLE_MODELS:
        raise ValueError("الوكيل غير معروف. استخدم auto أو claude أو gpt أو gemini")
    try:
        return _openrouter_agent(selected, task)
    except Exception:
        if requested == "auto" or selected == "claude":
            return _bedrock_manager(chat_id, task, bedrock_fallback, requested=requested, fallback=True)
        raise


def agents_status_text() -> str:
    status = models.status()
    return "\n".join([
        "🧠 AI Team v0.7",
        f"Claude — Manager/Orchestrator: {status['models']['manager']}",
        f"GPT — Critic: {status['models']['critic']}",
        f"Gemini — Researcher: {status['models']['google']}",
        f"OpenRouter: {'configured ✅' if status['openrouter_configured'] else 'not configured'}",
        f"Bedrock protected manager/fallback: {'configured ✅' if status['bedrock_configured'] else 'not configured'}",
        "Auto routing: Research→Gemini | Review/Risk→GPT | Management→Claude",
        "Shared objective: /mission الهدف — Claude decomposes, delegates, reconciles, and synthesizes.",
        "Tools: model reasoning only; external connectors/actions keep their existing approval rules.",
    ])


def council(chat_id: int, question: str, *, bedrock_fallback=None) -> str:
    task = (question or "").strip()
    if not task:
        raise ValueError("اكتب السؤال بعد /council")
    if contains_private_data(task):
        raise ValueError("AI Council لا يستقبل بيانات مريض أو معرّفات خاصة. أزل البيانات الخاصة أولًا.")

    answers: list[tuple[str, str, str]] = []
    failures: list[str] = []
    for agent in ("claude", "gpt", "gemini"):
        try:
            result = _openrouter_agent(agent, task)
            answers.append((agent, result.model, result.answer))
        except Exception as exc:
            failures.append(f"{ROLE_LABELS[agent]}: {models._safe_error(exc)}")

    if len(answers) < 2:
        if bedrock_fallback is None:
            raise RuntimeError("AI Council unavailable: fewer than two advisers responded")
        fallback = _bedrock_manager(
            chat_id,
            "The multi-agent council could not obtain two independent responses. Give a single-manager assessment and explicitly state that the council was unavailable.\n\n" + task,
            bedrock_fallback,
            requested="council",
            fallback=True,
        )
        detail = "\n".join(failures[:3])
        return f"⚠️ AI Council unavailable; Bedrock manager fallback used.\n{fallback.answer}\n\nTechnical status:\n{detail}"

    evidence = "\n\n".join(f"[{ROLE_LABELS[a]} | {m}]\n{answer}" for a, m, answer in answers)
    judge_prompt = (
        "Act as the council judge. Synthesize the independent adviser notes below. "
        "Return: consensus, disagreements, key risk/blind spot, recommendation, and confidence 0-100. "
        "Do not invent external evidence.\n\nQUESTION:\n" + task + "\n\nADVISERS:\n" + evidence
    )
    try:
        judge = _openrouter_agent("claude", judge_prompt, max_tokens=1100).answer
        judge_source = "Claude judge"
    except Exception:
        fallback = _bedrock_manager(chat_id, judge_prompt, bedrock_fallback, requested="council", fallback=True)
        judge = fallback.answer
        judge_source = "Bedrock judge fallback"
    failures_note = ("\n\nUnavailable adviser(s):\n" + "\n".join(failures)) if failures else ""
    return f"🧠 AI Council — {len(answers)}/3 advisers\nJudge: {judge_source}\n\n{judge}{failures_note}"


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(raw[start:end + 1])
                return value if isinstance(value, dict) else {}
            except Exception:
                pass
    return {}


def _default_mission_plan(objective: str) -> dict:
    return {
        "mission_summary": objective,
        "gemini_task": (
            "Explore the objective from a research/discovery perspective. Identify possible approaches, "
            "alternatives, evidence gaps, and what should be checked. Do not claim live web research unless "
            "evidence is supplied.\n\nOBJECTIVE:\n" + objective
        ),
        "gpt_task": (
            "Critically review the objective. Identify assumptions, risks, failure modes, trade-offs, decision "
            "criteria, and what must be verified before execution.\n\nOBJECTIVE:\n" + objective
        ),
        "success_criteria": ["clear recommendation", "major risks identified", "practical next actions"],
        "manager_focus": "Reconcile specialist findings into one accountable plan.",
    }


def _normalise_plan(plan: dict, objective: str) -> dict:
    fallback = _default_mission_plan(objective)
    if not isinstance(plan, dict):
        return fallback
    result = dict(fallback)
    for key in ("mission_summary", "gemini_task", "gpt_task", "success_criteria", "manager_focus"):
        value = plan.get(key)
        if value not in (None, "", []):
            result[key] = value
    if not isinstance(result["success_criteria"], list):
        result["success_criteria"] = [str(result["success_criteria"])]
    result["success_criteria"] = [str(x)[:300] for x in result["success_criteria"][:6]]
    return result


def _plan_mission(chat_id: int, objective: str, bedrock_fallback=None) -> tuple[dict, str]:
    planner_prompt = (
        "MISSION PLANNER. You are Claude, the manager/orchestrator. Decompose one shared objective into two "
        "complementary work packages: one for Gemini (research/discovery/alternatives) and one for GPT "
        "(critique/risk/verification). Keep yourself responsible for final synthesis. Do not assign external "
        "actions, do not claim browsing, and do not include secrets. Return JSON only with keys: mission_summary, "
        "gemini_task, gpt_task, success_criteria (array), manager_focus.\n\nOBJECTIVE:\n" + objective
    )
    try:
        result = _openrouter_agent(
            "claude", planner_prompt, max_tokens=700, temperature=0.1,
            response_format={"type": "json_object"},
        )
        return _normalise_plan(_extract_json_object(result.answer), objective), "Claude/OpenRouter"
    except Exception:
        if bedrock_fallback is None:
            return _default_mission_plan(objective), "deterministic fallback"
        fallback = _bedrock_manager(
            chat_id, planner_prompt, bedrock_fallback, requested="mission-plan", fallback=True,
        )
        return _normalise_plan(_extract_json_object(fallback.answer), objective), "Claude/Bedrock fallback"


def _run_mission_specialists(plan: dict) -> tuple[dict[str, AgentResult], list[str]]:
    work = {"gemini": str(plan["gemini_task"]), "gpt": str(plan["gpt_task"])}
    results: dict[str, AgentResult] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-mission") as pool:
        pending = {
            pool.submit(_openrouter_agent, agent, task, max_tokens=950, temperature=0.2): agent
            for agent, task in work.items()
        }
        for future in as_completed(pending):
            agent = pending[future]
            try:
                results[agent] = future.result()
            except Exception as exc:
                failures.append(f"{ROLE_LABELS[agent]}: {models._safe_error(exc)}")
    return results, failures


def _mission_evidence(results: dict[str, AgentResult]) -> str:
    ordered = []
    for agent in ("gemini", "gpt"):
        result = results.get(agent)
        if result:
            ordered.append(f"[{ROLE_LABELS[agent]} | {result.model}]\n{result.answer}")
    return "\n\n".join(ordered)


def mission(chat_id: int, objective: str, *, bedrock_fallback=None) -> str:
    """Run one shared objective through plan -> specialists -> manager synthesis."""
    goal = (objective or "").strip()
    if not goal:
        raise ValueError("اكتب الهدف بعد /mission")
    if contains_private_data(goal):
        raise ValueError(
            "المهمة المشتركة لا ترسل بيانات مريض أو معرّفات خاصة إلى GPT/Gemini. "
            "أزل المعرّفات أو استخدم المسار السريري المحمي مع Claude/Bedrock."
        )

    plan, planner_source = _plan_mission(chat_id, goal, bedrock_fallback=bedrock_fallback)
    specialist_results, failures = _run_mission_specialists(plan)

    if not specialist_results:
        fallback = _bedrock_manager(
            chat_id,
            "The shared-mission specialists were unavailable. Produce a protected single-manager plan for the "
            "objective, clearly stating that GPT and Gemini did not contribute. Return recommendation, risks, "
            "next actions, and approval needed.\n\nOBJECTIVE:\n" + goal,
            bedrock_fallback,
            requested="mission",
            fallback=True,
        )
        technical = "\n".join(failures[:2])
        return (
            "🎯 AI Mission v0.7\n"
            f"Objective: {goal}\nPlanner: {planner_source}\n"
            "Team result: ⚠️ specialists unavailable; protected Claude fallback used.\n\n"
            f"{fallback.answer}\n\nTechnical status:\n{technical}"
        )

    evidence = _mission_evidence(specialist_results)
    criteria = "\n".join(f"- {x}" for x in plan["success_criteria"])
    synthesis_prompt = (
        "MISSION SYNTHESIS. You are Claude, the accountable manager/orchestrator. Using the objective, your "
        "decomposition, and specialist outputs, produce ONE coherent management result. Explicitly distinguish: "
        "(1) Mission status, (2) What Gemini contributed, (3) What GPT challenged/verified, (4) Consensus, "
        "(5) Disagreements/uncertainty, (6) Manager recommendation, (7) Next actions with owner labels, "
        "(8) Approval needed from the user, (9) Confidence 0-100. Do not invent live external evidence and do not "
        "claim that any external action was executed.\n\n"
        f"OBJECTIVE:\n{goal}\n\nMANAGER FOCUS:\n{plan['manager_focus']}\n\n"
        f"SUCCESS CRITERIA:\n{criteria}\n\nSPECIALISTS:\n{evidence}"
    )
    try:
        manager = _openrouter_agent("claude", synthesis_prompt, max_tokens=1400, temperature=0.15)
        final_answer = manager.answer
        manager_source = f"Claude/OpenRouter | {manager.model}"
    except Exception:
        fallback = _bedrock_manager(
            chat_id, synthesis_prompt, bedrock_fallback, requested="mission", fallback=True,
        )
        final_answer = fallback.answer
        manager_source = f"Claude/Bedrock fallback | {fallback.model}"

    completed = ", ".join(ROLE_LABELS[a] for a in ("gemini", "gpt") if a in specialist_results)
    failures_note = ("\n\nUnavailable specialist(s):\n" + "\n".join(failures)) if failures else ""
    return (
        "🎯 AI Mission v0.7\n"
        f"Objective: {goal}\nPlanner: {planner_source}\n"
        f"Specialists completed: {completed}\nFinal manager: {manager_source}\n\n"
        f"{final_answer}{failures_note}"
    )

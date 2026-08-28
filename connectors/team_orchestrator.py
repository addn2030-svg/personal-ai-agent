# -*- coding: utf-8 -*-
"""Cooperative AI-team orchestration layered over the stable delegation engine.

Mission v0.8 changes /mission from parallel specialists to a real handoff:
Claude plan -> Gemini research package -> GPT cross-review -> Claude synthesis.
No external-action permissions are added here.
"""
from __future__ import annotations

import os

from . import model_gateway as models
from . import task_delegation as base

HANDOFF_MAX_CHARS = int(os.environ.get("AI_TEAM_HANDOFF_MAX_CHARS", "12000"))
MISSION_VERSION = "v0.8"


def _bounded_text(text: str, limit: int = HANDOFF_MAX_CHARS) -> str:
    """Bound a handoff without silently pretending it is complete."""
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    marker = "\n\n[HANDOFF_TRUNCATED: middle omitted to stay within context budget]\n\n"
    head = max(1, int(limit * 0.72))
    tail = max(1, limit - head - len(marker))
    return value[:head] + marker + value[-tail:]


def routed_agent(agent: str, task: str, *, max_tokens: int = 900,
                 temperature: float = 0.2, response_format: dict | None = None) -> base.AgentResult:
    """Call the existing gateway but report the provider that actually answered."""
    model = base.ROLE_MODELS[agent]()
    answer, _usage, _latency = models.openrouter_chat(
        model=model,
        messages=[
            {"role": "system", "content": base._system_for(agent)},
            {"role": "user", "content": task},
        ],
        sensitive=False,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    route = models.last_route()
    provider = str(route.get("provider") or "openrouter")
    actual_model = str(route.get("model") or model)
    return base.AgentResult(
        requested=agent,
        executed_by=agent,
        provider=provider,
        model=actual_model,
        answer=answer,
        fallback=bool(route.get("fallback", False)),
    )


def _plan_mission(chat_id: int, objective: str, bedrock_fallback=None) -> tuple[dict, str]:
    planner_prompt = (
        "MISSION PLANNER. You are Claude, the accountable manager/orchestrator. "
        "Plan a cooperative sequence, not two independent answers. Gemini must first create a compact research/"
        "alternatives package. GPT will then receive Gemini's package and cross-review it for evidence quality, "
        "risks, contradictions, assumptions, and decision readiness. You retain final synthesis responsibility. "
        "Return JSON only with keys: mission_summary, gemini_task, gpt_task, success_criteria (array), manager_focus. "
        "Do not assign external actions, claim browsing, or include secrets.\n\nOBJECTIVE:\n" + objective
    )
    try:
        result = routed_agent(
            "claude", planner_prompt, max_tokens=700, temperature=0.1,
            response_format={"type": "json_object"},
        )
        plan = base._normalise_plan(base._extract_json_object(result.answer), objective)
        return plan, f"Claude/{result.provider}"
    except Exception:
        if bedrock_fallback is None:
            return base._default_mission_plan(objective), "deterministic fallback"
        fallback = base._bedrock_manager(
            chat_id, planner_prompt, bedrock_fallback, requested="mission-plan", fallback=True,
        )
        plan = base._normalise_plan(base._extract_json_object(fallback.answer), objective)
        return plan, "Claude/Bedrock fallback"


def _run_handoff(objective: str, plan: dict) -> tuple[dict[str, base.AgentResult], list[str], bool]:
    """Run Gemini first, then give its actual output to GPT for cross-review."""
    results: dict[str, base.AgentResult] = {}
    failures: list[str] = []

    gemini_task = (
        str(plan["gemini_task"]) +
        "\n\nHANDOFF FORMAT REQUIREMENT:\n"
        "Produce a compact, complete package for the next specialist. Cover every requested problem/option, "
        "key assumptions, evidence gaps, practical solutions, risks, and proposed actions. Prefer concise tables "
        "or bullets over long prose. Do not stop after the first item. Keep the package under about 900 words."
    )
    try:
        results["gemini"] = routed_agent(
            "gemini", gemini_task, max_tokens=1350, temperature=0.2
        )
    except Exception as exc:
        failures.append(f"{base.ROLE_LABELS['gemini']}: {models._safe_error(exc)}")

    if "gemini" in results:
        gemini_handoff = _bounded_text(results["gemini"].answer)
        handoff_context = (
            "GEMINI HANDOFF — review this exact specialist output:\n" + gemini_handoff
        )
    else:
        handoff_context = (
            "GEMINI HANDOFF — unavailable. Perform a standalone risk/verification review of the objective and "
            "explicitly state that no Gemini output was available."
        )

    gpt_task = (
        str(plan["gpt_task"]) +
        "\n\nYou are the second specialist in a sequential handoff. Review Gemini's package below rather than producing "
        "an unrelated parallel answer. Identify: supported vs unsupported claims, missing evidence, contradictions, "
        "operational/clinical/governance risks, corrections, stronger alternatives, and decision criteria. "
        "Do not claim the Gemini output was missing or truncated unless the text explicitly says GEMINI HANDOFF — "
        "unavailable or contains [HANDOFF_TRUNCATED].\n\nOBJECTIVE:\n" + objective + "\n\n" + handoff_context
    )
    try:
        results["gpt"] = routed_agent(
            "gpt", gpt_task, max_tokens=1200, temperature=0.15
        )
    except Exception as exc:
        failures.append(f"{base.ROLE_LABELS['gpt']}: {models._safe_error(exc)}")

    return results, failures, "gemini" in results and "gpt" in results


def _mission_evidence(results: dict[str, base.AgentResult]) -> str:
    blocks: list[str] = []
    for agent in ("gemini", "gpt"):
        result = results.get(agent)
        if result:
            blocks.append(
                f"[{base.ROLE_LABELS[agent]} | provider={result.provider} | model={result.model}]\n"
                + _bounded_text(result.answer)
            )
    return "\n\n".join(blocks)


def mission(chat_id: int, objective: str, *, bedrock_fallback=None) -> str:
    """Run one objective through plan -> Gemini -> GPT cross-review -> Claude synthesis."""
    goal = (objective or "").strip()
    if not goal:
        raise ValueError("اكتب الهدف بعد /mission")
    if base.contains_private_data(goal):
        raise ValueError(
            "المهمة المشتركة لا ترسل بيانات مريض أو معرّفات خاصة إلى GPT/Gemini. "
            "أزل المعرّفات أو استخدم المسار السريري المحمي مع Claude/Bedrock."
        )

    plan, planner_source = _plan_mission(chat_id, goal, bedrock_fallback=bedrock_fallback)
    specialist_results, failures, handoff_ok = _run_handoff(goal, plan)

    if not specialist_results:
        fallback = base._bedrock_manager(
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
            f"🎯 AI Mission {MISSION_VERSION}\n"
            f"Objective: {goal}\nPlanner: {planner_source}\n"
            "Workflow: Claude → Gemini → GPT review → Claude\n"
            "Team result: ⚠️ specialists unavailable; protected Claude fallback used.\n\n"
            f"{fallback.answer}\n\nTechnical status:\n{technical}"
        )

    evidence = _mission_evidence(specialist_results)
    criteria = "\n".join(f"- {x}" for x in plan["success_criteria"])
    handoff_status = "COMPLETE: GPT received Gemini output" if handoff_ok else "PARTIAL: one specialist unavailable"
    synthesis_prompt = (
        "MISSION SYNTHESIS. You are Claude, the accountable manager/orchestrator. This is a sequential cooperative "
        "mission, not parallel voting. Gemini generated the first specialist package; when both specialists are "
        "present, GPT received and cross-reviewed that Gemini package. Produce ONE coherent management result. "
        "Explicitly distinguish: (1) Mission status, (2) Gemini contribution, (3) GPT cross-review/corrections, "
        "(4) Consensus after review, (5) Remaining disagreements/uncertainty, (6) Manager recommendation, "
        "(7) Next actions with owner labels, (8) Approval needed, (9) Confidence 0-100. Do not say an output was "
        "missing or truncated unless the evidence explicitly says so. Do not invent live external evidence or "
        "claim external actions were executed.\n\n"
        f"OBJECTIVE:\n{goal}\n\nHANDOFF STATUS:\n{handoff_status}\n\n"
        f"MANAGER FOCUS:\n{plan['manager_focus']}\n\nSUCCESS CRITERIA:\n{criteria}\n\n"
        f"SPECIALIST CHAIN:\n{evidence}"
    )
    try:
        manager = routed_agent("claude", synthesis_prompt, max_tokens=1500, temperature=0.12)
        final_answer = manager.answer
        manager_source = f"Claude/{manager.provider} | {manager.model}"
    except Exception:
        fallback = base._bedrock_manager(
            chat_id, synthesis_prompt, bedrock_fallback, requested="mission", fallback=True,
        )
        final_answer = fallback.answer
        manager_source = f"Claude/bedrock | {fallback.model}"

    completed = ", ".join(
        f"{base.ROLE_LABELS[a]} [{specialist_results[a].provider}]"
        for a in ("gemini", "gpt") if a in specialist_results
    )
    failures_note = ("\n\nUnavailable specialist(s):\n" + "\n".join(failures)) if failures else ""
    return (
        f"🎯 AI Mission {MISSION_VERSION}\n"
        f"Objective: {goal}\nPlanner: {planner_source}\n"
        "Workflow: Claude → Gemini → GPT cross-review → Claude\n"
        f"Handoff Gemini→GPT: {'✅' if handoff_ok else '⚠️ partial'}\n"
        f"Specialists completed: {completed}\nFinal manager: {manager_source}\n\n"
        f"{final_answer}{failures_note}"
    )


def agents_status_text() -> str:
    status = models.status()
    openai_direct = bool(getattr(models, "direct_openai_configured", lambda: False)())
    gemini_direct = bool(getattr(models, "direct_gemini_configured", lambda: False)())
    return "\n".join([
        f"🧠 AI Team {MISSION_VERSION}",
        f"Claude — Manager/Orchestrator: {status['models']['manager']}",
        f"GPT — Critic: {status['models']['critic']} | direct OpenAI {'✅' if openai_direct else 'not configured'}",
        f"Gemini — Researcher: {status['models']['google']} | direct Gemini {'✅' if gemini_direct else 'not configured'}",
        f"OpenRouter fallback: {'configured ✅' if status['openrouter_configured'] else 'not configured'}",
        f"Bedrock protected manager/fallback: {'configured ✅' if status['bedrock_configured'] else 'not configured'}",
        "Auto routing: Research→Gemini | Review/Risk→GPT | Management→Claude",
        "Mission workflow: Claude plan → Gemini research → GPT cross-review → Claude synthesis.",
        "Tools: model reasoning only; external connectors/actions keep their existing approval rules.",
    ])


def install() -> None:
    """Patch the legacy-compatible module so Telegram keeps the same import surface."""
    if getattr(base, "_mission_handoff_v08_installed", False):
        return
    base._openrouter_agent = routed_agent
    base.mission = mission
    base.agents_status_text = agents_status_text
    base._mission_handoff_v08_installed = True

# -*- coding: utf-8 -*-
"""Validated, dependency-free contracts for the Smart Agent's core behaviour.

``agent_prompt.yaml`` is intentionally JSON-formatted YAML. JSON is valid YAML
1.2, so people with PyYAML can inspect it as YAML while the production runtime
remains dependency-free and can validate the file with Python's standard library.

The contracts are deliberately *defaults*, not a second source for secrets or
runtime credentials:

* environment variables remain the deployment override for model credentials and
  provider-specific configuration;
* this module owns persona, memory limits, model-tier defaults and hard safety
  boundaries that are safe to keep in version control;
* malformed or incomplete contracts fail at import/startup instead of silently
  dropping a safety or budget setting.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
PROMPT_PATH = BASE / "agent_prompt.yaml"
CONFIG_PATH = BASE / "config.json"


class ContractError(RuntimeError):
    """Raised when a versioned agent contract is missing or unsafe to use."""


def _load_json_contract(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{label} is missing or unreadable: {path.name}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{label} must be JSON-formatted YAML/JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain one object")
    return value


def _positive_int(value: Any, label: str) -> int:
    # bool is an int subclass but never a safe limit.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ContractError(f"{label} must be a positive number")
    return float(value)


def _required_text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ContractError(f"{label} is required")
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a non-empty list")
    result = [str(item).strip() for item in value if str(item).strip()]
    if not result:
        raise ContractError(f"{label} must be a non-empty list")
    return result


@lru_cache(maxsize=1)
def load_prompt_contract() -> dict[str, Any]:
    """Load and validate the versioned persona, memory and escalation contract."""
    data = _load_json_contract(PROMPT_PATH, "agent_prompt.yaml")
    agent = data.get("agent")
    memory = data.get("memory")
    escalation = data.get("escalation")
    if not isinstance(agent, dict):
        raise ContractError("agent_prompt.yaml.agent must be an object")
    if not isinstance(memory, dict):
        raise ContractError("agent_prompt.yaml.memory must be an object")
    if not isinstance(escalation, dict):
        raise ContractError("agent_prompt.yaml.escalation must be an object")

    name = _required_text(agent.get("name"), "agent.name")
    role = _required_text(agent.get("role"), "agent.role")
    language = _required_text(agent.get("default_language"), "agent.default_language")
    hard_rules = _string_list(agent.get("hard_rules"), "agent.hard_rules")

    working_turns = _positive_int(memory.get("working_turns_verbatim"), "memory.working_turns_verbatim")
    session_turns = _positive_int(memory.get("session_turns_persisted"), "memory.session_turns_persisted")
    summarize_after = _positive_int(memory.get("summarize_after_turns"), "memory.summarize_after_turns")
    if summarize_after > session_turns:
        raise ContractError("memory.summarize_after_turns cannot exceed session_turns_persisted")
    long_term = memory.get("long_term")
    if not isinstance(long_term, dict):
        raise ContractError("memory.long_term must be an object")
    top_k = _positive_int(long_term.get("top_k"), "memory.long_term.top_k")
    min_score = long_term.get("min_score")
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)) or not 0 <= float(min_score) <= 1:
        raise ContractError("memory.long_term.min_score must be between 0 and 1")
    if not isinstance(long_term.get("enabled"), bool):
        raise ContractError("memory.long_term.enabled must be boolean")
    if not isinstance(long_term.get("promotion_requires_review"), bool):
        raise ContractError("memory.long_term.promotion_requires_review must be boolean")

    confirm_when = _string_list(escalation.get("confirm_when"), "escalation.confirm_when")
    return {
        "version": _required_text(data.get("version"), "version"),
        "agent": {
            "name": name,
            "role": role,
            "default_language": language,
            "hard_rules": hard_rules,
        },
        "memory": {
            "working_turns_verbatim": working_turns,
            "session_turns_persisted": session_turns,
            "summarize_after_turns": summarize_after,
            "long_term": {
                "enabled": long_term["enabled"],
                "promotion_requires_review": long_term["promotion_requires_review"],
                "top_k": top_k,
                "min_score": float(min_score),
            },
        },
        "escalation": {"confirm_when": confirm_when},
    }


@lru_cache(maxsize=1)
def load_runtime_config() -> dict[str, Any]:
    """Load and validate safe model-tier defaults and the cost-budget envelope."""
    data = _load_json_contract(CONFIG_PATH, "config.json")
    models = data.get("models")
    budget = data.get("budget")
    runtime = data.get("runtime")
    if not isinstance(models, dict) or not models:
        raise ContractError("config.json.models must be a non-empty object")
    if not isinstance(budget, dict):
        raise ContractError("config.json.budget must be an object")
    if not isinstance(runtime, dict):
        raise ContractError("config.json.runtime must be an object")

    validated_models: dict[str, dict[str, Any]] = {}
    for profile, settings in models.items():
        profile_name = _required_text(profile, "models profile name")
        if not isinstance(settings, dict):
            raise ContractError(f"models.{profile_name} must be an object")
        temperature = settings.get("temperature")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
            raise ContractError(f"models.{profile_name}.temperature must be between 0 and 2")
        validated_models[profile_name] = {
            "provider": _required_text(settings.get("provider"), f"models.{profile_name}.provider"),
            "model": _required_text(settings.get("model"), f"models.{profile_name}.model"),
            "temperature": float(temperature),
            "max_output_tokens": _positive_int(
                settings.get("max_output_tokens"), f"models.{profile_name}.max_output_tokens"
            ),
        }
    if "general" not in validated_models:
        raise ContractError("config.json.models.general is required")

    max_tokens_per_turn = _positive_int(budget.get("max_tokens_per_turn"), "budget.max_tokens_per_turn")
    for profile, settings in validated_models.items():
        if settings["max_output_tokens"] > max_tokens_per_turn:
            raise ContractError(
                f"models.{profile}.max_output_tokens cannot exceed budget.max_tokens_per_turn"
            )
    if not isinstance(budget.get("hard_stop_on_budget"), bool):
        raise ContractError("budget.hard_stop_on_budget must be boolean")
    if not isinstance(runtime.get("mock_tools"), bool):
        raise ContractError("runtime.mock_tools must be boolean")

    return {
        "version": _required_text(data.get("version"), "version"),
        "models": validated_models,
        "budget": {
            "max_daily_spend_usd": _positive_number(budget.get("max_daily_spend_usd"), "budget.max_daily_spend_usd"),
            "max_tokens_per_turn": max_tokens_per_turn,
            "max_tool_calls_per_turn": _positive_int(
                budget.get("max_tool_calls_per_turn"), "budget.max_tool_calls_per_turn"
            ),
            "hard_stop_on_budget": budget["hard_stop_on_budget"],
        },
        "runtime": {
            "environment": _required_text(runtime.get("environment"), "runtime.environment"),
            "mock_tools": runtime["mock_tools"],
            "log_level": _required_text(runtime.get("log_level"), "runtime.log_level"),
        },
    }


def reset_cache() -> None:
    """Test/support hook for a deliberate contract reload after a controlled edit."""
    load_prompt_contract.cache_clear()
    load_runtime_config.cache_clear()


def memory_limits() -> dict[str, int]:
    """Return the source-controlled conversation retention limits."""
    memory = load_prompt_contract()["memory"]
    return {
        "working_turns_verbatim": memory["working_turns_verbatim"],
        "session_turns_persisted": memory["session_turns_persisted"],
        "summarize_after_turns": memory["summarize_after_turns"],
    }


def model_defaults(profile: str = "general") -> dict[str, Any]:
    """Get one model profile, falling back only to the validated general profile."""
    models = load_runtime_config()["models"]
    return dict(models.get(str(profile or "").lower()) or models["general"])


def model_name(profile: str = "general") -> str:
    return str(model_defaults(profile)["model"])


def inference_defaults(profile: str = "general") -> tuple[int, float]:
    settings = model_defaults(profile)
    return int(settings["max_output_tokens"]), float(settings["temperature"])


def render_system_contract() -> str:
    """Render the active contract for the model-facing system instruction.

    The string holds only public policy configuration. It intentionally excludes
    credentials, state contents and deployment-specific endpoints.
    """
    prompt = load_prompt_contract()
    agent = prompt["agent"]
    memory = prompt["memory"]
    hard_rules = "\n".join(f"- {rule}" for rule in agent["hard_rules"])
    escalation = ", ".join(prompt["escalation"]["confirm_when"])
    return (
        "\n\nVERSIONED AGENT CONTRACT — this policy is authoritative.\n"
        f"Identity: {agent['name']} — {agent['role']}\n"
        f"Default language: {agent['default_language']} (follow the user's language when they choose another).\n"
        "Hard rules:\n"
        f"{hard_rules}\n"
        "Memory contract: retain up to "
        f"{memory['working_turns_verbatim']} recent working turns verbatim; "
        f"session retention is bounded to {memory['session_turns_persisted']} messages; "
        "long-term facts require review before promotion.\n"
        f"Confirmation is required for: {escalation}."
    )


# Validate both source-controlled contracts eagerly. Configuration errors must be
# discovered on startup, not after a model call or an attempted external action.
load_prompt_contract()
load_runtime_config()

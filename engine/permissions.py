# -*- coding: utf-8 -*-
"""Central capability policy for Abdulrahman AI OS v0.5.
Read is broad; external side effects are denied by default unless explicitly allowed.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Decision:
    allowed: bool
    needs_approval: bool
    reason: str

POLICY = {
    "chief_of_staff": {"read_state", "read_knowledge", "draft", "route", "enqueue_action"},
    "projects": {"read_state", "read_knowledge", "draft", "update_state"},
    "learning": {"read_state", "read_knowledge", "draft", "update_state"},
    "research": {"read_state", "read_knowledge", "draft"},
    "health": {"read_state", "read_knowledge", "draft", "update_state"},
    "finance": {"read_state", "read_knowledge", "draft", "update_state"},
    "clinical": {"read_state", "read_knowledge", "draft"},
    "social": {"read_state", "read_knowledge", "draft", "enqueue_action"},
    "communications": {"read_state", "draft", "enqueue_action"},
    "executor": {"execute_approved"},
}

SENSITIVE_DOMAINS = {"clinical", "health", "finance"}
EXTERNAL_CAPABILITIES = {"send_message", "publish", "book", "pay", "delete_external", "execute_approved"}


def authorize(agent: str, capability: str, approved: bool = False) -> Decision:
    caps = POLICY.get(agent, set())
    if capability in EXTERNAL_CAPABILITIES:
        if agent != "executor":
            return Decision(False, True, "external effects must go through executor + approval queue")
        if not approved:
            return Decision(False, True, "executor requires a recorded human approval")
        return Decision(True, False, "approved external execution")
    if capability not in caps:
        return Decision(False, False, f"{agent} lacks capability {capability}")
    if agent in SENSITIVE_DOMAINS and capability == "update_state":
        return Decision(True, False, "local state update only; no external action")
    return Decision(True, False, "allowed")


def matrix():
    return {k: sorted(v) for k, v in POLICY.items()}

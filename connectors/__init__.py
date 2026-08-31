"""Live connector adapters for Abdulrahman AI OS."""

from . import model_gateway as model_gateway
from .direct_specialists import install as _install_direct_specialists
from .provider_diagnostics import install as _install_provider_diagnostics

_install_direct_specialists(model_gateway)
_install_provider_diagnostics(model_gateway)

# v0.8 keeps the cooperative handoff implementation available for council/deep
# fallbacks and backward compatibility.
from .team_orchestrator import install as _install_team_orchestrator

_install_team_orchestrator()

# v0.9 is the active /mission surface: Bedrock-first, conditional delegation,
# compact packets, explicit token budgets, and optional Arena/GitHub capsules.
from .lean_missions import install as _install_lean_missions

_install_lean_missions()

# v0.9.3 adds a tiny operational context capsule only for objectives that need
# current priorities/calendar/tasks. It does not restore full history/context.
from .ops_context import install as _install_ops_context

_install_ops_context()

# v0.9.6 routes explicit natural-language scheduling requests to the guarded
# Calendar proposal flow before the general AI path. Writes still require
# /confirm_event approval.
from .calendar_intent import install as _install_calendar_intent

_install_calendar_intent()

# WO-8 upgrades Telegram capture from one-label classification to conservative
# multi-intent recording in StateStore. It does not execute external actions.
from .multi_intent_runtime import install as _install_multi_intent_runtime

_install_multi_intent_runtime()

# Capability Truth makes runtime/tool capability authoritative instead of asking
# the language model to guess. It also installs the stricter privacy classifier so
# generic phrases such as "physical therapy" do not become clinical-private logs.
from .capability_runtime import install as _install_capability_runtime

_install_capability_runtime()

# Natural Action Executor turns bounded natural-language operational requests into
# preview -> approval -> execution -> receipt without replacing Telegram/webhook.
from .action_runtime import install as _install_action_runtime

_install_action_runtime()

# Adds simple deadline/date-time language, Calendar reminders after approval,
# and read-only project reports sent directly to the authorized Telegram chat.
from .action_deadline_report import install as _install_action_deadline_report

_install_action_deadline_report()

# Explicit negation (e.g. "لا يوجد تذكير") must outrank reminder keywords.
from .action_language_safety import install as _install_action_language_safety

_install_action_language_safety()

# Executive Brief v3 discovers non-task operating context from Sheets + StateStore:
# constraints, logistics rules, commitments, decision criteria, financial boundaries,
# and capability/status changes. Read-only discovery; no external action is executed.
from .brief_signal_runtime import install as _install_brief_signal_runtime

_install_brief_signal_runtime()

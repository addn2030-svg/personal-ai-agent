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

# Hotfix: ground statements about the configured Main Sheet in a live read-only
# connector probe. This corrects false "no Sheets API / no access" answers while
# preserving approval-gated writes and making no claim about arbitrary sheet URLs.
from .capability_hotfix import install as _install_capability_hotfix

_install_capability_hotfix()

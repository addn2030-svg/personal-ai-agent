"""Live connector adapters for Abdulrahman AI OS."""

from . import model_gateway as model_gateway
from .direct_specialists import install as _install_direct_specialists
from .provider_diagnostics import install as _install_provider_diagnostics

_install_direct_specialists(model_gateway)
_install_provider_diagnostics(model_gateway)

from .team_orchestrator import install as _install_team_orchestrator
_install_team_orchestrator()

from .lean_missions import install as _install_lean_missions
_install_lean_missions()

from .ops_context import install as _install_ops_context
_install_ops_context()

from .calendar_intent import install as _install_calendar_intent
_install_calendar_intent()

from .multi_intent_runtime import install as _install_multi_intent_runtime
_install_multi_intent_runtime()

from .capability_runtime import install as _install_capability_runtime
_install_capability_runtime()

from .action_runtime import install as _install_action_runtime
_install_action_runtime()

from .action_deadline_report import install as _install_action_deadline_report
_install_action_deadline_report()

from .action_language_safety import install as _install_action_language_safety
_install_action_language_safety()

# Commerce Agent is read-only during deal scouting. Order execution stays behind
# preview + approval and requires a separate trusted checkout connector/receipt.
from .commerce_runtime import install as _install_commerce_runtime
_install_commerce_runtime()

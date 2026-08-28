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

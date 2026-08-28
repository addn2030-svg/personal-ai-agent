"""Live connector adapters for Abdulrahman AI OS."""

from . import model_gateway as model_gateway
from .direct_specialists import install as _install_direct_specialists
from .provider_diagnostics import install as _install_provider_diagnostics

_install_direct_specialists(model_gateway)
_install_provider_diagnostics(model_gateway)

# Keep the existing task_delegation import surface, but upgrade /mission to the
# sequential cooperative handoff: Claude -> Gemini -> GPT -> Claude.
from .team_orchestrator import install as _install_team_orchestrator

_install_team_orchestrator()

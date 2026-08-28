"""Live connector adapters for Abdulrahman AI OS."""

from . import model_gateway as model_gateway
from .direct_specialists import install as _install_direct_specialists
from .provider_diagnostics import install as _install_provider_diagnostics

_install_direct_specialists(model_gateway)
_install_provider_diagnostics(model_gateway)

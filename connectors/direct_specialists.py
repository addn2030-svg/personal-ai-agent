# -*- coding: utf-8 -*-
"""Legacy import shim. All model calls are routed through OmniRoute."""
from __future__ import annotations

def install(gateway) -> None:
    """Retained for compatibility; the gateway itself is the sole model route."""
    return None

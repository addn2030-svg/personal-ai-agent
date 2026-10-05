# -*- coding: utf-8 -*-
"""Compatibility shim for the centralized OmniRoute gateway."""
from __future__ import annotations

def combined_provider_error(provider: str, direct_error: Exception, fallback_error: Exception) -> RuntimeError:
    return RuntimeError(f"OmniRoute request failed: {str(fallback_error)[:240]}")

def install(gateway) -> None:
    """No provider patching is needed when all inference uses OmniRoute."""
    return None

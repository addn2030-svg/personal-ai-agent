# -*- coding: utf-8 -*-
"""Provider diagnostics helpers for specialist routing."""
from __future__ import annotations


def combined_provider_error(provider: str, direct_error: Exception, fallback_error: Exception) -> RuntimeError:
    direct = str(direct_error)[:320]
    fallback = str(fallback_error)[:180]
    return RuntimeError(
        f"{provider} direct failed: {direct}; OpenRouter fallback failed: {fallback}"
    )

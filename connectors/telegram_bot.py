# -*- coding: utf-8 -*-
"""Guarded compatibility entrypoint for the legacy Telegram polling implementation.

Production imports this module normally, but polling is disabled unless explicitly
opted in with AI_OS_ALLOW_POLLING=1. The implementation lives in
telegram_bot_legacy.py so the guard cannot be bypassed by an accidental run() call.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import telegram_bot_legacy as _impl

_legacy_run = _impl.run


def _guarded_run():
    if os.environ.get("AI_OS_ALLOW_POLLING", "").strip() != "1":
        raise RuntimeError(
            "Telegram polling is disabled. Production uses webhook mode. "
            "Set AI_OS_ALLOW_POLLING=1 only for an explicit local polling session."
        )
    return _legacy_run()


_impl.run = _guarded_run

if __name__ == "__main__":
    _guarded_run()
else:
    # Make importers receive the implementation module itself. This preserves its
    # global state and lets runtime patches (_append, _category, handle_message, ...)
    # modify the same globals used by the implementation functions.
    sys.modules[__name__] = _impl

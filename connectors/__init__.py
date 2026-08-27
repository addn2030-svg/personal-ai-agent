"""Live connector adapters for Abdulrahman AI OS."""
from __future__ import annotations

import os
import sys

# Production already has a working authenticated Apps Script webhook. Prefer it
# for Google knowledge access so Railway does not depend on a service-account
# JSON. Local/test environments without the webhook keep the existing adapter.
if os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip() and os.environ.get(
    "GOOGLE_SHEETS_WEBHOOK_SECRET", ""
).strip():
    from . import google_knowledge_webhook as _google_knowledge_webhook

    sys.modules[__name__ + ".google_knowledge"] = _google_knowledge_webhook

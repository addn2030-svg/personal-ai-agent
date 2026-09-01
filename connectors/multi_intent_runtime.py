# -*- coding: utf-8 -*-
"""Runtime adapter that upgrades Telegram capture to WO-8 multi-intent recording.

No external action is executed here. The adapter only writes linked operational
records into StateStore. It deliberately leaves Calendar preview/confirm and all
other approval gates unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ENGINE = BASE / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from . import telegram_bot_legacy as legacy


def install() -> None:
    if getattr(legacy, "_wo8_multi_intent_installed", False):
        return

    original_save_intake = legacy._save_intake

    def multi_local_capture(text: str, message: dict, kind: str):
        try:
            from unified_inbox import add, classify_and_record

            ref = f"telegram:{message.get('message_id', '')}"
            iid = add(
                "TELEGRAM",
                text,
                kind=kind,
                source_ref=ref,
                sensitive=legacy._clinical_hint(text),
                metadata={"chat_id": str((message.get("chat") or {}).get("id", ""))},
            )
            classify_and_record(iid, text, kind=kind, source="TELEGRAM", source_ref=ref)
            return iid
        except Exception as exc:
            print(f"WO-8 local intake capture error: {exc}", flush=True)
            return f"TG-{(message.get('chat') or {}).get('id','')}-{message.get('message_id','')}"

    def multi_save_intake(iid, message, text, kind, attachment, status, response_id="", error=""):
        # Voice/audio are initially captured as *_PENDING_TRANSCRIPTION. Once the
        # transcript exists, this second idempotent pass records its real intents.
        try:
            value = str(text or "").strip()
            if value and not value.startswith("[VOICE_PENDING_") and not value.startswith("[AUDIO_PENDING_"):
                from unified_inbox import classify_and_record

                ref = f"telegram:{message.get('message_id', '')}"
                classify_and_record(iid, value, kind=kind, source="TELEGRAM", source_ref=ref)
        except Exception as exc:
            # Structured recording is fail-soft for the user-facing response; the
            # error is logged, but it never causes an external action.
            print(f"WO-8 classify/record warning: {exc}", flush=True)
        return original_save_intake(
            iid, message, text, kind, attachment, status, response_id=response_id, error=error
        )

    legacy._local_capture = multi_local_capture
    legacy._save_intake = multi_save_intake
    legacy._wo8_multi_intent_installed = True

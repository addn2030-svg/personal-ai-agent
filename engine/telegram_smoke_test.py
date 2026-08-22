# -*- coding: utf-8 -*-
"""Send one explicit test message to the already-claimed Telegram owner.
Requires TELEGRAM_BOT_TOKEN and data/.telegram-owner. No token/chat id is printed.
Usage: TELEGRAM_BOT_TOKEN=... python3 engine/telegram_smoke_test.py لون
"""
import os, sys
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(BASE,"engine"))
import telegram_bot

def main():
    text=" ".join(sys.argv[1:]).strip() or "لون"
    chat=telegram_bot.owner_id()
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("TELEGRAM_BOT_TOKEN غير مضبوط")
    if not chat:
        raise SystemExit("لا يوجد مالك بعد — أرسل /start للبوت أولاً")
    r=telegram_bot.api("sendMessage",chat_id=chat,text=text)
    ok=bool(r and r.get("ok"))
    print("✅ Telegram smoke test sent" if ok else "❌ Telegram smoke test failed; check data/audit.jsonl")
    return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Telegram connector health probe. Does not send messages."""
import json, os, urllib.request
TOKEN=os.environ.get('TELEGRAM_BOT_TOKEN','')

def doctor():
    if not TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN is not set')
    data=json.loads(urllib.request.urlopen(f'https://api.telegram.org/bot{TOKEN}/getMe',timeout=20).read())
    if not data.get('ok'): raise RuntimeError(str(data)[:300])
    r=data['result']; return {'id':r.get('id'),'username':r.get('username'),'can_join_groups':r.get('can_join_groups')}

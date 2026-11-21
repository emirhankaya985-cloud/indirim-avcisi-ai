"""Only declare successful delivery after Telegram confirms ok=true."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def send_message(body: str) -> tuple[bool, str]:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return False, 'TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing'
    payload = json.dumps({'chat_id': chat_id, 'text': body[:3900], 'disable_web_page_preview': True}).encode('utf-8')
    req = Request(f'https://api.telegram.org/bot{token}/sendMessage',
                  data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=20) as response:
            answer = json.loads(response.read(1_000_000))
        if answer.get('ok') is True and answer.get('result', {}).get('message_id'):
            return True, str(answer['result']['message_id'])
        return False, f'Telegram rejected message: {str(answer.get("description", "unknown"))[:120]}'
    except Exception as exc:
        return False, f'Telegram request failed: {type(exc).__name__}'

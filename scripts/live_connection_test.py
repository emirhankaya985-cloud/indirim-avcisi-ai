"""Explicit production connection test. No test prices or coupon rows are inserted."""
from datetime import datetime, timezone
from pathlib import Path
import os
from tracker.storage import load,persist,is_neon_enabled
from tracker.production import sender


def main():
    if not is_neon_enabled():
        print('BLOCKED: NEON_DATABASE_URL missing')
        return 2
    if not (os.getenv('NTFY_TOPIC','').strip() or
            (os.getenv('TELEGRAM_BOT_TOKEN','').strip() and os.getenv('TELEGRAM_CHAT_ID','').strip())):
        print('BLOCKED: notification credentials missing')
        return 2
    now=datetime.now(timezone.utc)
    key=now.date().isoformat()
    path=Path('data/state.json')
    try:
        state,version=load(path)
        records=state.setdefault('connection_tests',{})
        if key in records:
            print('Existing test for UTC date: '+records[key]['status']+'; not resent')
            return 0 if records[key]['status']=='accepted' else 1
        channel='ntfy' if os.getenv('NTFY_TOPIC','').strip() else 'telegram'
        records[key]={'status':'attempt_reserved','time':now.isoformat(),'channel':channel}
        state['connection_tests']=dict(sorted(records.items())[-90:])
        persist(path,state,version)
        state,version=load(path)
        if state.get('connection_tests',{}).get(key,{}).get('status')!='attempt_reserved':
            print('BLOCKED: test reservation not persisted')
            return 1
        print('Neon write/read verified (diagnostic only)')
        ok,receipt=sender('TEST — İndirim Avcısı AI bağlantı kontrolü. Bu bir gerçek fırsat bildirimi değildir.')
        row=state['connection_tests'][key]
        row['status']='accepted' if ok else 'unconfirmed'
        if ok:
            row['receipt']=receipt
        persist(path,state,version)
        reread,_=load(path)
        saved=reread.get('connection_tests',{}).get(key,{})
        if ok and saved.get('receipt')==receipt and saved.get('status')=='accepted':
            print(channel+' API accepted; receipt stored and read back (not proof of phone display)')
            return 0
        print(channel+' delivery unconfirmed; no automatic test resend')
        return 1
    except Exception as exc:
        print('Connection test failed: '+type(exc).__name__)
        return 1


if __name__=='__main__':
    raise SystemExit(main())

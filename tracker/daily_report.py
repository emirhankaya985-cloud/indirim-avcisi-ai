"""Read-only Turkish daily health report; no prices or secrets in public logs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
from urllib.request import Request, build_opener

from .network import _NoRedirect
from .storage import load, is_neon_enabled
from .telegram import send_message


def render(state, config, enabled, now, storage_ok):
    cutoff = now - timedelta(hours=24)
    runs = []
    for row in state.get('run_log', []):
        try:
            at = datetime.fromisoformat(row['time'])
            if cutoff <= at <= now:
                runs.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    failures = sum(bool(r.get('errors')) for r in runs)
    products = len(config.get('products', []))
    feeds = len(config.get('coupon_feeds', []))
    scans = sum(r.get('products_ok', 0) for r in runs)
    feed_reads = sum(r.get('feeds_ok', 0) for r in runs)
    blocked = not enabled or not storage_ok or not products
    status = ('ENGELLİ' if blocked else 'VERİ YOK' if not runs
              else 'KONTROL GEREKLİ' if failures or not scans or len(runs) < 48
              else 'KAYITLI TARAMALAR VAR')
    return '\n'.join([
        'İndirim Avcısı AI — Günlük durum raporu',
        now.astimezone(ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M Türkiye'),
        f'Durum: {status}',
        f'Otomasyon: {"açık" if enabled else "kapalı"}',
        f'Neon: {"okuma başarılı" if storage_ok else "doğrulanamadı"}',
        f'Tanımlı ürün: {products} | Kupon akışı: {feeds}',
        f'Son 24 saatte kayıtlı tarama: {len(runs)} (hedef 48, garanti değil)',
        f'Başarılı ürün okumaları: {scans} | Akış okumaları: {feed_reads}',
        f'Hatalı tarama: {failures} | API kabul edilen alarm: {sum(r.get("sent", 0) for r in runs)}',
        f'Bekleyen alarm: {len(state.get("pending", []))}' if storage_ok else 'Bekleyen alarm: bilinmiyor',
        'Kupon adayları ödeme ekranında doğrulanmış değildir.',
        'Neon okunamadığında sayımlar mevcut kayıtları temsil etmez.' if not storage_ok
        else 'Sayımlar yalnızca saklanan çalışma kayıtlarına dayanır.',
    ])


def send_ntfy(body, env=None):
    env = os.environ if env is None else env
    topic = env.get('NTFY_TOPIC', '').strip()
    if not topic:
        return False, 'ntfy yapılandırılmamış'
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,64}', topic):
        return False, 'ntfy topic geçersiz'
    headers = {'Content-Type': 'text/plain; charset=utf-8'}
    if env.get('NTFY_TOKEN'):
        headers['Authorization'] = 'Bearer ' + env['NTFY_TOKEN']
    try:
        req = Request('https://ntfy.sh/' + topic, data=body.encode('utf-8'),
                      headers=headers, method='POST')
        with build_opener(_NoRedirect()).open(req, timeout=20) as response:
            result = json.loads(response.read(65536))
            if response.status == 200 and result.get('event') == 'message' and result.get('id'):
                return True, 'ntfy API kabul etti'
    except Exception:
        pass
    return False, 'ntfy gönderimi doğrulanamadı'


def main():
    try:
        config = json.loads(Path('config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    state, storage_ok = {}, False
    if is_neon_enabled():
        try:
            state, _ = load(Path('data/state.json'))
            storage_ok = True
        except RuntimeError:
            pass
    enabled = os.getenv('TRACKING_ENABLED') == 'true'
    body = render(state, config, enabled, datetime.now(timezone.utc), storage_ok)
    telegram_ok, _ = send_message(body)
    ntfy_configured = bool(os.getenv('NTFY_TOPIC', '').strip())
    ntfy_ok = send_ntfy(body)[0] if ntfy_configured else None
    print('Telegram API kabulü: ' + ('evet' if telegram_ok else 'hayır'))
    print('ntfy API kabulü: ' + ('evet' if ntfy_ok else 'hayır' if ntfy_configured else 'yapılandırılmamış'))
    print('Neon okuma: ' + ('başarılı' if storage_ok else 'doğrulanamadı'))
    return 0 if telegram_ok and storage_ok and (not ntfy_configured or ntfy_ok) else 1


if __name__ == '__main__':
    raise SystemExit(main())

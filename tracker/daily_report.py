"""Turkish daily and weekly health report; no prices or secrets in public logs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import os
import re
from urllib.request import Request, build_opener

from .network import _NoRedirect
from .storage import load, persist, is_neon_enabled
from .telegram import send_message


def render(state, config, enabled, now, storage_ok, days=1):
    cutoff = now - timedelta(days=days)
    runs = []
    for row in state.get('run_log', []):
        try:
            at = datetime.fromisoformat(row['time'])
            if cutoff <= at <= now:
                runs.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    failures = sum(bool(r.get('errors')) for r in runs)
    active_sources = {s.get('url') for s in config.get('catalog_sources', []) if s.get('authorized') is True}
    tracked_urls = {p.get('url') for p in config.get('products', [])}
    tracked_urls.update(p.get('url') for p in state.get('catalog', {}).values() if p.get('source') in active_sources)
    products = len(tracked_urls)
    feeds = len(config.get('coupon_feeds', []))
    scans = sum(r.get('products_ok', 0) for r in runs)
    feed_reads = sum(r.get('feeds_ok', 0) for r in runs)
    blocked = not enabled or not storage_ok or not products
    status = ('ENGELLİ' if blocked else 'VERİ YOK' if not runs
              else 'KONTROL GEREKLİ' if failures or not scans or len(runs) < 48*days
              else 'KAYITLI TARAMALAR VAR')
    def total(key):
        return str(sum(r[key] for r in runs)) if storage_ok and runs and all(key in r for r in runs) else 'bilinmiyor'
    best = []
    by_id = dict(state.get('catalog', {}))
    by_id.update({p.get('id'): p for p in config.get('products', [])})
    platform_errors = {}
    for pid, p in by_id.items():
        if p.get('url') not in tracked_urls:
            continue
        item = state.get('products', {}).get(pid, {})
        if item.get('last_error'):
            host = urlsplit(p.get('url', '')).hostname or 'bilinmiyor'
            platform_errors[host] = platform_errors.get(host, 0) + 1
            continue
        try:
            at = datetime.fromisoformat(item['last_checked'])
            metrics = item['metrics']
            if cutoff <= at <= now and metrics.get('score') is not None and Decimal(metrics['saving']) > 0:
                best.append((metrics['score'], p.get('name', pid), metrics['saving'], metrics['currency']))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    best.sort(reverse=True)
    opportunities = '; '.join(f'{name[:60]}: {saving} {currency} (puan {score})' for score,name,saving,currency in best[:3])
    return '\n'.join([
        'İndirim Avcısı AI — Günlük durum raporu' if days == 1 else 'İndirim Avcısı AI — Haftalık fırsat özeti',
        now.astimezone(ZoneInfo('Europe/Istanbul')).strftime('%d.%m.%Y %H:%M Türkiye'),
        f'Durum: {status}',
        f'Otomasyon: {"açık" if enabled else "kapalı"}',
        f'Neon: {"okuma başarılı" if storage_ok else "doğrulanamadı"}',
        f'Tanımlı ürün: {products} | Kupon akışı: {feeds}',
        f'Son {days*24} saatte kayıtlı tarama: {len(runs)} (hedef {48*days}, garanti değil)' if storage_ok else 'Son 24 saatte tarama: bilinmiyor',
        f'Başarılı ürün okumaları: {scans} | Akış okumaları: {feed_reads}' if storage_ok else 'Başarılı ürün/akış okumaları: bilinmiyor',
        f'Yeni keşif: {total("discovered")} | İndirim: {total("price_alerts")} | Kupon adayı: {total("coupon_candidates")}',
        f'Başarısız bildirim: {total("notification_failed")}',
        'Başarısız fiyat okumaları: ' + (str(sum(r['products_attempted']-r['products_ok'] for r in runs)) if storage_ok and runs and all('products_attempted' in r and 'products_ok' in r for r in runs) else 'bilinmiyor'),
        'Son bilinen ürün erişim hataları: ' + (', '.join(f'{k}: {v}' for k,v in sorted(platform_errors.items())) or ('kayıt yok' if storage_ok and runs else 'bilinmiyor')),
        'En iyi kayıtlı fiyat düşüşleri: ' + (opportunities or 'doğrulanmış veri yok'),
        'GitHub zamanlayıcı ve güncel faturalama/kota: bağımsız doğrulama gerekli',
        f'Hatalı tarama: {failures} | API kabul edilen alarm: {sum(r.get("sent", 0) for r in runs)}' if storage_ok else 'Hatalı tarama / API kabulü: bilinmiyor',
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
                return True, 'ntfy:' + str(result['id'])
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
            state, version = load(Path('data/state.json'))
            storage_ok = True
        except RuntimeError:
            pass
    enabled = os.getenv('TRACKING_ENABLED') == 'true'
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Europe/Istanbul'))
    report_key = local.date().isoformat()
    if storage_ok and report_key in state.get('report_receipts', {}):
        print('Daily report already accepted by API; not resent')
        return 0
    body = render(state, config, enabled, now, storage_ok)
    if local.weekday() == 0:
        body += '\n\n' + render(state, config, enabled, now, storage_ok, days=7)
    ntfy_configured = bool(os.getenv('NTFY_TOPIC', '').strip())
    ok, receipt = send_ntfy(body) if ntfy_configured else send_message(body)
    channel = 'ntfy' if ntfy_configured else 'telegram'
    print(channel + ' API kabulü: ' + ('evet' if ok else 'hayır'))
    print('Neon okuma: ' + ('başarılı' if storage_ok else 'doğrulanamadı'))
    if ok and storage_ok:
        records = state.setdefault('report_receipts', {})
        records[report_key] = {'channel': channel, 'receipt': receipt, 'time': now.isoformat()}
        state['report_receipts'] = dict(list(records.items())[-90:])
        try:
            persist(Path('data/state.json'), state, version)
        except RuntimeError:
            print('Report accepted, but receipt persistence failed')
            return 1
    return 0 if storage_ok and ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Price history, coupon lead detection, and at-least-once notifications."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import tempfile

from .extract import coupon_entries, extract_price
from .network import Downloader, validate_url
from .telegram import send_message

MARKETPLACES = ['trendyol.com', 'amazon.com.tr', 'hepsiburada.com', 'n11.com']


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(now: datetime) -> str:
    return now.isoformat(timespec='seconds')


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return deepcopy(default)
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.state-', suffix='.tmp', delete=False) as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write('\n')
        temp_name = stream.name
    os.replace(temp_name, path)


def _validate_entries(config: dict) -> None:
    product_ids = set()
    for p in config.get('products', []):
        product_id = p.get('id', '')
        if not re.fullmatch('[a-zA-Z0-9_-]{2,50}', str(product_id)) or product_id in product_ids:
            raise ValueError('Each product needs a unique id (2-50 ASCII characters)')
        product_ids.add(product_id)
        if not isinstance(p.get('name'), str) or not p['name'].strip():
            raise ValueError(f'Product {product_id} needs a name')
        validate_url(p['url'], MARKETPLACES)
        if p.get('currency', 'TRY') not in ('TRY', 'USD', 'EUR'):
            raise ValueError('Unsupported currency')
        threshold = Decimal(str(p.get('drop_percent', 5)))
        if not Decimal('0.5') <= threshold <= Decimal('90'):
            raise ValueError('drop_percent must be 0.5..90')
    feed_ids = set()
    for f in config.get('coupon_feeds', []):
        feed_id = f.get('id', '')
        if not re.fullmatch('[a-zA-Z0-9_-]{2,50}', str(feed_id)) or feed_id in feed_ids:
            raise ValueError('Each coupon feed needs a unique ID')
        feed_ids.add(feed_id)
        parts = __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(f['url'])
        host = (parts.hostname or '').lower()
        if not host or '.' not in host or host.endswith(('.local', '.internal', '.localhost', '.test')):
            raise ValueError('Coupon feed must be on a public HTTPS domain')
        validate_url(f['url'], [host])
        if not f.get('name'):
            raise ValueError('Coupon feed needs name')
    if not config.get('products') and not config.get('coupon_feeds'):
        raise ValueError('At least one actual product URL or coupon RSS/Atom feed is required')


def _prune(samples: list[dict], now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=90)
    kept = []
    for item in samples:
        try:
            dt = datetime.fromisoformat(item['time'])
            if dt.tzinfo and dt >= cutoff:
                kept.append(item)
        except (ValueError, KeyError, TypeError):
            continue
    return kept[-9000:]


def update_price(state: dict, product: dict, price: Decimal, now: datetime, evidence: str) -> bool:
    pid = product['id']
    existing = state.setdefault('products', {}).setdefault(pid, {'samples': []})
    samples = _prune(existing.get('samples', []), now)
    prev = Decimal(existing['last_price']) if existing.get('last_price') else None
    recent = [Decimal(s['price']) for s in samples
              if datetime.fromisoformat(s['time']) >= now - timedelta(days=30)]
    past_low = min(recent) if recent else None
    threshold = Decimal(str(product.get('drop_percent', 5)))
    cooldown = timedelta(hours=int(product.get('cooldown_hours', 24)))
    last_alert = datetime.fromisoformat(existing['last_alert_at']) if existing.get('last_alert_at') else None
    qualifies = (prev is not None and price <= prev * (Decimal('1') - threshold / Decimal('100'))
                 and (past_low is None or price < past_low)
                 and (last_alert is None or now - last_alert >= cooldown))
    if qualifies:
        change = (prev - price) / prev * 100
        body = (f'📉 FİYAT DÜŞTÜ | {product["name"][:100]}\n'
                f'Önceki: {prev:.2f} {product.get("currency", "TRY")}\n'
                f'Yeni: {price:.2f} {product.get("currency", "TRY")} | -%{change:.1f}\n'
                f'Tasarruf: {prev-price:.2f} {product.get("currency", "TRY")}\n'
                f'Son 30 günün kayıtlı en düşük önceki fiyatı: {past_low if past_low is not None else "bilinmiyor"}\n'
                f'Kaynak: {evidence}; ürün sayfası\n{product["url"]}\n'
                f'Not: Fiyat sepette değişebilir; otomatik satın alma yok.')
        key = sha256(f'price:{pid}:{price}:{timestamp(now)}'.encode()).hexdigest()[:20]
        state.setdefault('pending', []).append({'id': key, 'type': 'price', 'body': body,
                                                 'created_at': timestamp(now), 'attempts': 0})
        existing['last_alert_at'] = timestamp(now)
    if not samples or Decimal(samples[-1]['price']) != price or samples[-1]['time'][:10] != now.date().isoformat():
        samples.append({'time': timestamp(now), 'price': str(price),
                        'currency': product.get('currency', 'TRY'), 'evidence': evidence})
    existing['all_time_low'] = str(min([price] + [Decimal(s['price']) for s in samples] +
                                       ([Decimal(existing['all_time_low'])] if existing.get('all_time_low') else [])))
    existing.update({'samples': samples, 'last_price': str(price),
                     'last_checked': timestamp(now), 'currency': product.get('currency', 'TRY'),
                     'evidence': evidence, 'last_error': None})
    return qualifies


def update_feed(state: dict, feed: dict, parsed: list[dict[str, str]], now: datetime) -> int:
    record = state.setdefault('feeds', {}).setdefault(feed['id'], {})
    seen = record.get('seen', [])
    current_keys = []
    for entry in parsed:
        current_keys.append(sha256(entry['id'].encode('utf-8')).hexdigest()[:24])
    new_count = 0
    already_queued = {x.get('id') for x in state.get('pending', [])}
    already_delivered = {x.get('id') for x in state.get('delivery_log', [])}
    within_this_feed = set()
    if record.get('initialized'):
        for entry, key in zip(parsed, current_keys):
            notice_id = 'feed:' + feed['id'] + ':' + key
            if key not in seen and key not in within_this_feed and notice_id not in already_queued and notice_id not in already_delivered:
                body = (f'🎟️ KUPON ADAYI (DOĞRULANMADI)\n'
                        f'{feed["name"][:100]}: {entry["title"][:150]}\n'
                        f'Kaynak: {entry["link"] or feed["url"]}\n'
                        f'Kodun geçerliliği ve ödeme ekranı indirimi doğrulanmadı.')
                state.setdefault('pending', []).append({'id': notice_id,
                                                         'type': 'coupon_candidate', 'body': body,
                                                         'created_at': timestamp(now), 'attempts': 0})
                new_count += 1
                within_this_feed.add(key)
    record['seen'] = list(dict.fromkeys(current_keys + seen))[:1000]
    record.update({'initialized': True, 'last_checked': timestamp(now), 'last_error': None})
    return new_count


def dispatch_pending(state: dict, sender=send_message, current_time: datetime | None = None) -> tuple[int, int]:
    """Send at most 20 due alerts. Failed attempts back off up to 24 h."""
    now = current_time or now_utc()
    sent = failed = 0
    remaining = []
    for item in state.get('pending', []):
        retry_at = item.get('next_attempt_at')
        if (sent + failed >= 20) or (retry_at and datetime.fromisoformat(retry_at) > now):
            remaining.append(item)
            continue
        try:
            ok, info = sender(item['body'])
        except Exception as exc:
            # A transport exception must never discard a pending notification.
            # Do not interpolate exception messages: they may contain tokens/URLs.
            ok, info = False, f'Telegram transport exception: {type(exc).__name__}'
        if ok:
            sent += 1
            state.setdefault('delivery_log', []).append({
                'id': item['id'], **({'channel': 'ntfy', 'message_id': info[5:]} if info.startswith('ntfy:') else
                                    {'channel': 'telegram', 'telegram_message_id': info}), 'sent_at': timestamp(now)})
        else:
            failed += 1
            item['attempts'] = item.get('attempts', 0) + 1
            item['last_error'] = info
            wait = min(24 * 60, 30 * 2 ** min(item['attempts'] - 1, 6))
            item['next_attempt_at'] = timestamp(now + timedelta(minutes=wait))
            remaining.append(item)
    state['pending'] = remaining
    state['delivery_log'] = state.get('delivery_log', [])[-100:]
    return sent, failed


def execute(config: dict, old_state: dict, downloader=None, sender=send_message,
            current_time: datetime | None = None, dry_run: bool = False) -> tuple[dict, dict]:
    _validate_entries(config)
    now = current_time or now_utc()
    state = deepcopy(old_state)
    downloader = downloader or Downloader()
    count = {'products_ok': 0, 'feeds_ok': 0, 'price_alerts': 0,
             'coupon_candidates': 0, 'sent': 0, 'pending': 0, 'errors': []}
    for p in config.get('products', []):
        try:
            raw = downloader.read(p['url'], MARKETPLACES, respect_robots=True)
            price = extract_price(raw.decode('utf-8', errors='replace'), p.get('currency', 'TRY'))
            # Preserve the public product URL with each evidence record in Neon.
            if update_price(state, p, price.amount, now,
                            f'{price.evidence}; url={p["url"]}'):
                count['price_alerts'] += 1
            count['products_ok'] += 1
        except Exception as exc:
            msg = f'Product {p["id"]}: {type(exc).__name__}: {str(exc)[:170]}'
            count['errors'].append(msg)
            state.setdefault('products', {}).setdefault(p['id'], {})['last_error'] = msg
    for f in config.get('coupon_feeds', []):
        try:
            from urllib.parse import urlsplit
            domain = urlsplit(f['url']).hostname
            raw = downloader.read(f['url'], [domain], respect_robots=True)
            count['coupon_candidates'] += update_feed(state, f, coupon_entries(raw), now)
            count['feeds_ok'] += 1
        except Exception as exc:
            msg = f'Feed {f["id"]}: {type(exc).__name__}: {str(exc)[:170]}'
            count['errors'].append(msg)
            state.setdefault('feeds', {}).setdefault(f['id'], {})['last_error'] = msg
    if not dry_run:
        sent, failed = dispatch_pending(state, sender, current_time=now)
        count['sent'] = sent
        if failed:
            count['errors'].append(f'{failed} Telegram notifications failed; retained for retry')
    count['pending'] = len(state.get('pending', []))
    if count['products_ok'] > 0:
        state['last_successful_price_scan'] = timestamp(now)
    state['last_run'] = timestamp(now)
    state['last_summary'] = count
    state.setdefault('run_log', []).append({
        'time': timestamp(now), 'products_ok': count['products_ok'],
        'feeds_ok': count['feeds_ok'], 'sent': count['sent'],
        'errors': count['errors'][:10]})
    state['run_log'] = state['run_log'][-100:]
    return state, count

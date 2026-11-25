"""Bounded production tick; persist the outbox before contacting notification APIs."""
from pathlib import Path
from datetime import timezone, datetime
import os
import json

from .discovery import discover, due, batch_products, validate_source
from .analytics import comparable_offers
from .engine import execute, dispatch_pending
from .network import Downloader
from .storage import load, persist, is_neon_enabled
from .daily_report import send_ntfy
from .telegram import send_message


def sender(body):
    # No automatic fallback after an ambiguous network failure (duplicate risk).
    return send_ntfy(body) if os.getenv('NTFY_TOPIC', '').strip() else send_message(body)


def tick(config, state, downloader, now):
    errors = []
    added = 0
    sources = config.get('catalog_sources', [])
    if sources and due(state.get('last_discovery_attempt'), now, 2):
        added, errors = discover(state, sources, downloader, now)
        state['last_discovery_attempt'] = now.isoformat()
    # Removed or revoked sources must never be used for ongoing page access.
    active_urls = {s['url'] for s in sources}
    eligible = {k: v for k, v in state.get('catalog', {}).items() if v.get('source') in active_urls}
    rotation = {'catalog': eligible, 'catalog_cursor': state.get('catalog_cursor', 0)}
    products = batch_products(rotation, config.get('products', []))
    state['catalog_cursor'] = rotation.get('catalog_cursor', 0)
    feeds = []
    if due(state.get('last_coupon_attempt'), now, 3):
        feeds = config.get('coupon_feeds', [])[:10]
        state['last_coupon_attempt'] = now.isoformat()
    if products or feeds:
        future, counts = execute({'products': products, 'coupon_feeds': feeds},
                                 state, downloader=downloader, current_time=now, dry_run=True, strict=True)
    else:
        future = state
        counts = {'products_ok': 0, 'feeds_ok': 0, 'price_alerts': 0,
                  'coupon_candidates': 0, 'sent': 0, 'errors': []}
        future.setdefault('run_log', []).append({'time': now.isoformat()})
        future['run_log'] = future['run_log'][-400:]
    counts['errors'].extend(errors)
    if not products:
        counts['errors'].append('No eligible product in catalog')
    counts['discovered'] = added
    counts['products_attempted'] = len(products)
    counts['pending'] = len(future.get('pending', []))
    future['comparison_candidates'] = comparable_offers(eligible, future.get('products', {}), now)[:500]
    future['last_run'] = now.isoformat()
    future['last_summary'] = counts
    future['run_log'][-1].update(counts)
    return future, counts


def main():
    if os.getenv('TRACKING_ENABLED') != 'true' or not is_neon_enabled():
        print('BLOCKED: tracking flag or Neon secret absent')
        return 2
    if not (os.getenv('NTFY_TOPIC', '').strip() or
            (os.getenv('TELEGRAM_BOT_TOKEN', '').strip() and os.getenv('TELEGRAM_CHAT_ID', '').strip())):
        print('BLOCKED: notification channel absent')
        return 2
    try:
        config = json.loads(Path('config.json').read_text(encoding='utf-8'))
        for source in config.get('catalog_sources', []):
            validate_source(source)
        for feed in config.get('coupon_feeds', []):
            if feed.get('authorized') is not True or not feed.get('permission_reference'):
                raise ValueError('Coupon source permission required')
        path = Path('data/state.json')
        state, version = load(path)
        if not (config.get('products') or config.get('catalog_sources') or state.get('catalog')):
            print('BLOCKED: no authorized product source')
            return 2
        now = datetime.now(timezone.utc)
        future, counts = tick(config, state, Downloader(), now)
        # Durable pending notifications before sending; optimistic versioning.
        persist(path, future, version)
        sent, failed = dispatch_pending(future, sender, current_time=now)
        counts.update(sent=sent, notification_failed=failed, pending=len(future.get('pending', [])))
        future['last_summary'] = counts
        future['run_log'][-1].update(counts)
        if failed:
            counts['errors'].append('Notification delivery unconfirmed')
        persist(path, future, version + 1)
        print(json.dumps({k: v for k, v in counts.items() if k != 'errors'}, ensure_ascii=False))
        print('Error count:', len(counts['errors']))
        return 1 if counts['errors'] else 0
    except Exception as exc:
        print('Production tick failed:', type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

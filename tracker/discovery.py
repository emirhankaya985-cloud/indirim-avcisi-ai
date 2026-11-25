"""Authorized catalog discovery. No implicit marketplace scraping or invented products."""
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit
import json

from .network import validate_url
from .engine import MARKETPLACES

CATEGORIES = ('telefon', 'elektronik', 'oyuncu', 'ev', 'ev-aletleri',
              'giyim', 'bakim', 'supermarket', 'genel')
MAX_PRODUCTS = 500


def due(last, now, hours):
    if not last:
        return True
    try:
        return now - datetime.fromisoformat(last) >= timedelta(hours=hours)
    except (ValueError, TypeError):
        return True


def validate_source(source):
    if (source.get('authorized') is not True or
            source.get('product_page_access_authorized') is not True or
            source.get('history_storage_authorized') is not True):
        raise ValueError('Source permissions not confirmed')
    if not source.get('permission_reference'):
        raise ValueError('Source permission evidence required')
    if source.get('format') != 'catalog-json-v1':
        raise ValueError('Unsupported catalog format')
    host = urlsplit(source['url']).hostname
    validate_url(source['url'], [host])
    if urlsplit(source['url']).query:
        raise ValueError('Secret-bearing catalog URLs are not supported')
    return host


def discover(state, sources, downloader, now, limit=MAX_PRODUCTS):
    catalog = state.setdefault('catalog', {})
    errors, added = [], 0
    known = {p['url'] for p in catalog.values()}
    for source in sources[:10]:
        if len(catalog) >= limit:
            break
        try:
            host = validate_source(source)
            raw = downloader.read(source['url'], [host], respect_robots=True)
            entries = json.loads(raw)
            if not isinstance(entries, list):
                raise ValueError('Catalog must be a JSON list')
            for item in entries[:2000]:
                if len(catalog) >= limit:
                    break
                try:
                    if not isinstance(item, dict):
                        continue
                    url = item['url']
                    validate_url(url, MARKETPLACES)
                    if urlsplit(url).fragment or url in known:
                        continue
                    category = item.get('category')
                    name = item.get('name')
                    if category not in CATEGORIES or not isinstance(name, str) or not name.strip():
                        continue
                    pid = 'auto_' + sha256(url.encode()).hexdigest()[:24]
                    if pid in catalog:
                        continue
                    record = {'id': pid, 'name': name[:150], 'url': url,
                              'category': category, 'currency': 'TRY',
                              'discovered_at': now.isoformat(), 'source': source['url']}
                    for field in ('gtin', 'brand', 'model', 'variant', 'capacity', 'seller'):
                        if isinstance(item.get(field), str) and item[field].strip():
                            record[field] = item[field].strip()[:150]
                    catalog[pid] = record
                    known.add(url)
                    added += 1
                except (KeyError, TypeError, ValueError):
                    continue
        except Exception as exc:
            errors.append('Catalog source: ' + type(exc).__name__)
    return added, errors


def batch_products(state, manual, limit=12):
    # Manual entries take precedence; discovered entries persist in Neon.
    by_url = {p['url']: p for p in state.get('catalog', {}).values()}
    by_url.update({p['url']: p for p in manual})
    products = sorted(by_url.values(), key=lambda p: p['id'])
    if not products:
        return []
    start = state.get('catalog_cursor', 0) % len(products)
    size = min(limit, len(products))
    state['catalog_cursor'] = (start + size) % len(products)
    return [products[(start + i) % len(products)] for i in range(size)]

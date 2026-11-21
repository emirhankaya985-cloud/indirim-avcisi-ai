"""Public marketplace integration smoke test; never modifies watchlist/Neon."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
from tracker.extract import extract_price
from tracker.network import Downloader

PRODUCTS = [
    ('Trendyol','Gamepower Ogre Red Switch','https://www.trendyol.com/gamepower/ogre-rgb-60m-red-switch-usb-mekanik-gaming-klavye-p-33707213'),
    ('Hepsiburada','Logitech G203 LIGHTSYNC','https://www.hepsiburada.com/logitech-g203-lightsync-rgb-mouse-pm-HB00000X8001'),
    ('Amazon Türkiye','Logitech M90','https://www.amazon.com.tr/Logitech-Kablolu-Diz%C3%BCst%C3%BC-Bilgisayar-Kullan%C4%B1ma/dp/B003D8ZT0C'),
]

def run():
    observed = datetime.now(timezone.utc).isoformat(timespec='seconds')
    results = []
    downloader = Downloader()
    for store, title, url in PRODUCTS:
        row = {'store': store, 'product': title, 'url': url, 'observed_at_utc': observed, 'status': 'error'}
        try:
            host = urlsplit(url).hostname
            raw = downloader.read(url, [host], respect_robots=True)
            price = extract_price(raw.decode('utf-8', errors='replace'), 'TRY')
            row.update(status='ok', price=str(price.amount), currency=price.currency, evidence=price.evidence)
        except Exception as exc:
            row.update(error_type=type(exc).__name__, reason=str(exc)[:120])
        results.append(row)
    report = {'kind': 'diagnostic_marketplace_smoke_only', 'tracked_products': 0,
              'github_run_id': os.getenv('GITHUB_RUN_ID'), 'observed_at_utc': observed,
              'successful_price_reads': sum(x['status']=='ok' for x in results),
              'products': results}
    dest = Path('reports/live-marketplace-smoke.json')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"Live prices read: {report['successful_price_reads']}/{len(PRODUCTS)}")
    return 0 if report['successful_price_reads']==len(PRODUCTS) else 1

if __name__ == '__main__':
    raise SystemExit(run())

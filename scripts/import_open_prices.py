"""Import licensed dated Open Prices observations, never current merchant offers."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import json

from tracker.network import Downloader
from tracker.storage import _connection, is_neon_enabled
from tracker.analytics import gtin_key
from scripts.probe_open_prices import BASE, HOST

MAX_RECORDS = 5000
MAX_FETCH = 100


def normalize(row, today):
    try:
        if row.get('currency') != 'TRY' or row.get('price_per') is not None:
            return None
        code = row['product_code']
        if not gtin_key(code):
            return None
        ids = [row[k] for k in ('id', 'location_id', 'proof_id')]
        if any(type(v) is not int or v <= 0 for v in ids):
            return None
        observed = date.fromisoformat(row['date'])
        if not today-timedelta(days=90) <= observed <= today:
            return None
        amount = Decimal(str(row['price']))
        if not amount.is_finite() or not 0 < amount <= 100000000:
            return None
        if amount != amount.quantize(Decimal('0.01')):
            return None
        discount = row.get('price_is_discounted')
        if type(discount) is not bool or row.get('duplicate_of') is not None:
            return None
        product = row.get('product') or {}
        location = row.get('location') or {}
        country = location.get('osm_address_country_code')
        if country is not None and str(country).upper() != 'TR':
            return None
        name = row.get('product_name') or product.get('product_name')
        store = location.get('osm_name') or location.get('osm_brand')
        if not isinstance(name,str) or not name.strip() or not isinstance(store,str) or not store.strip():
            return None
        return (ids[0], code, ids[1], ids[2], observed, amount, 'TRY',
                name[:200], store[:150], discount, BASE+'/'+str(ids[0]))
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        return None


def fetch(today, downloader=None):
    params={'location__osm_address_country_code':'TR','currency':'TRY',
            'duplicate_of__isnull':'true','size':MAX_FETCH,
            'date__gte':(today-timedelta(days=90)).isoformat()}
    raw=(downloader or Downloader()).read(BASE+'?'+urlencode(params),[HOST],respect_robots=True)
    data=json.loads(raw)
    items=data['items']
    if not isinstance(items,list) or len(items)>MAX_FETCH or type(data['total']) is not int:
        raise ValueError('Unexpected source response')
    rows=[normalize(row,today) for row in items]
    return [r for r in rows if r is not None],len(items),data['total']


def main():
    if not is_neon_enabled():
        print('BLOCKED: NEON_DATABASE_URL missing')
        return 2
    try:
        rows,returned,total=fetch(datetime.now(timezone.utc).date())
        inserted=0
        with _connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM open_prices_observations')
            existing=cur.fetchone()[0]
            for row in rows[:max(0,MAX_RECORDS-existing)]:
                cur.execute('INSERT INTO open_prices_observations(source_id,product_code,location_id,proof_id,observed_date,price,currency,product_name,store_name,source_discount_flag,source_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_id) DO NOTHING',row)
                inserted+=cur.rowcount
        with _connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*),count(DISTINCT product_code),max(observed_date) FROM open_prices_observations')
            count,products,latest=cur.fetchone()
        print(json.dumps({'kind':'dated_open_prices_observations_not_live_offers',
                          'license':'ODbL — Open Prices / Open Food Facts',
                          'source_total_90_days':total,'returned':returned,'accepted':len(rows),
                          'inserted':inserted,'stored_observations':count,'stored_products':products,
                          'latest_observation_date':str(latest) if latest else None,
                          'capacity_reached':count>=MAX_RECORDS,'partial_source_page':total>returned}))
        return 0 if rows and count else 1
    except Exception as exc:
        print('Open Prices import unverified: '+type(exc).__name__)
        return 1


if __name__=='__main__':
    raise SystemExit(main())

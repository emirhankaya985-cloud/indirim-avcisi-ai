"""Read-only, two-request source suitability probe; only public product observation fields, no contributor data."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import json
from tracker.network import Downloader

HOST = 'prices.openfoodfacts.org'
BASE = 'https://' + HOST + '/api/v1/prices'


def main():
    d=Downloader()
    cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat()
    base={'location__osm_address_country_code':'TR','currency':'TRY',
          'duplicate_of__isnull':'true','size':10}
    for name,params in [('all',base),('last_30_days',dict(base,date__gte=cutoff))]:
        try:
            raw=d.read(BASE+'?'+urlencode(params),[HOST],respect_robots=True)
            data=json.loads(raw)
            rows=data['items']
            valid=[r for r in rows if r.get('currency')=='TRY' and r.get('proof_id') and r.get('product_code') and r.get('location_id')]
            print(json.dumps({'window':name,'total':data['total'],'sample_rows':len(rows),
                  'sample_with_barcode_location_proof':len(valid),
                  'sample_dates':sorted({str(r.get('date')) for r in rows})},ensure_ascii=False))
            if name=='last_30_days':
                for row in valid:
                    product=row.get('product') or {}
                    location=row.get('location') or {}
                    safe={k:row.get(k) for k in ('id','product_code','location_id','proof_id','date','price','price_per','currency','price_is_discounted')}
                    safe['product_name']=row.get('product_name') or product.get('product_name')
                    safe['store_name']=location.get('osm_name') or location.get('osm_brand')
                    print('PUBLIC_OBSERVATION '+json.dumps(safe,ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'window':name,'status':'unverified','error_type':type(exc).__name__}))
            return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())

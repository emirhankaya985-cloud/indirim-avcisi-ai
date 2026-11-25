"""Conservative observed-price analytics, no merchant list-price assumptions."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re


def price_metrics(samples, price, previous, now, historic_low=None):
    price = Decimal(price)
    result = {'current': str(price), 'previous': str(previous) if previous is not None else None,
              'currency': None, 'saving': None, 'drop_percent': None,
              'score': None, 'historical_low': None, 'fake_discount_suspicion': None,
              'stock': None, 'shipping': None, 'total_with_shipping': None}
    prior = []
    for sample in samples:
        try:
            at = datetime.fromisoformat(sample['time'])
            amount = Decimal(sample['price'])
            if at < now and amount.is_finite() and amount > 0:
                prior.append((at, amount))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue
    for days in (7, 30, 90):
        relevant = [amount for at, amount in prior if at >= now-timedelta(days=days)]
        result[f'low_{days}d'] = str(min([price] + relevant))
        result[f'prior_low_{days}d'] = str(min(relevant)) if relevant else None
        result[f'observations_{days}d'] = len(relevant) + 1
    lows = [price]+[a for _,a in prior]
    if historic_low is not None:
        lows.append(Decimal(historic_low))
    result['historical_low'] = str(min(lows))
    if previous is not None and Decimal(previous) > 0:
        prev = Decimal(previous)
        saving = prev-price
        drop = saving/prev*100
        result['saving'] = str(saving.quantize(Decimal('0.01')))
        result['drop_percent'] = str(drop.quantize(Decimal('0.01')))
        # Explainable score; historical dip requires prior evidence.
        if prior:
            low30 = result['prior_low_30d']
            score = min(70, max(0, int(drop*2)))
            if low30 is not None and price < Decimal(low30):
                score += 30
            result['score'] = min(100, score)
            # A fall that returns to or exceeds the recent low can be a rebound.
            if saving > 0 and low30 is not None and price >= Decimal(low30):
                result['fake_discount_suspicion'] = 'prior_low_not_beaten'
            else:
                result['fake_discount_suspicion'] = None
    return result


def gtin_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}|\d{12}|\d{13}|\d{14}', value):
        return None
    digits = [int(c) for c in value]
    total = sum(n*(3 if i%2==0 else 1) for i,n in enumerate(reversed(digits[:-1])))
    return value.zfill(14) if (10-total%10)%10==digits[-1] else None


def exact_match(a,b):
    # Never fuzzy-match names or compare conflicting attributes.
    g = gtin_key(a.get('gtin'))
    if not g or g != gtin_key(b.get('gtin')):
        return False
    for k in ('brand','model','variant','capacity'):
        x,y = a.get(k),b.get(k)
        if bool(x) != bool(y):
            return False
        if x and x.strip().casefold()!=y.strip().casefold():
            return False
    return True


def comparable_offers(catalog, products, now, max_age_hours=24):
    rows = []
    for pid,p in catalog.items():
        observation = products.get(pid, {})
        try:
            at = datetime.fromisoformat(observation['last_checked'])
            if observation.get('last_error') or not timedelta(0) <= now-at <= timedelta(hours=max_age_hours):
                continue
            price = Decimal(observation['last_price'])
            if price <= 0 or not price.is_finite() or not observation.get('evidence'):
                continue
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue
        rows.append((p,price,observation.get('currency')))
    pairs=[]
    for i,(a,pa,ca) in enumerate(rows):
        for b,pb,cb in rows[i+1:]:
            if ca and ca==cb and exact_match(a,b):
                pairs.append({'left':a['id'],'right':b['id'],'left_price':str(pa),
                              'right_price':str(pb),'currency':ca,
                              'shipping_included':False})
    return pairs

"""Strict production offer extraction; reject ambiguous prices and missing currency."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from .extract import MetadataParser, _types, _walk, to_decimal, Price


@dataclass(frozen=True)
class Observation:
    price: Price
    stock: str | None = None
    seller: str | None = None
    shipping: Decimal | None = None


class StrictMetadata(MetadataParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            info = dict(attrs)
            for field in ('property','name','itemprop'):
                if info.get(field) and info.get('content'):
                    self.values.setdefault(info[field].lower(), set()).add(info['content'])
        super().handle_starttag(tag, attrs)


def _shipping(offer, currency):
    details = offer.get('shippingDetails')
    if not isinstance(details, dict):
        return None
    destination = details.get('shippingDestination')
    if not isinstance(destination, dict) or destination.get('addressCountry') != 'TR':
        return None
    if set(destination) - {'@type','addressCountry'}:
        return None
    if set(details) - {'@type','shippingDestination','shippingRate','deliveryTime'}:
        return None
    rate = details.get('shippingRate')
    if not isinstance(rate, dict) or rate.get('currency') != currency:
        return None
    try:
        amount = Decimal(str(rate['value']))
        if amount.is_finite() and 0 <= amount <= 1000000:
            return amount.quantize(Decimal('0.01'))
    except (KeyError, InvalidOperation, ValueError):
        pass
    return None


def extract_observation(html, currency='TRY'):
    parser = StrictMetadata()
    parser.feed(html)
    products = []
    for script in parser.scripts:
        try:
            products.extend(n for n in _walk(json.loads(script)) if 'product' in _types(n))
        except (ValueError, TypeError):
            continue
    if products:
        if len(products) != 1:
            raise ValueError('Ambiguous product data')
        offer = products[0].get('offers')
        if isinstance(offer, list) and len(offer)==1:
            offer=offer[0]
        if not isinstance(offer, dict) or (_types(offer) and _types(offer) != {'offer'}):
            raise ValueError('Ambiguous or aggregate offer')
        if str(offer.get('priceCurrency','')).upper()!=currency:
            raise ValueError('Explicit matching offer currency required')
        price = Price(to_decimal(offer.get('price')), currency, 'Single Product/Offer JSON-LD')
        availability = str(offer.get('availability','')).split('/')[-1].lower()
        stock = {'instock':'in_stock','outofstock':'out_of_stock','soldout':'out_of_stock',
                 'limitedavailability':'limited','preorder':'preorder','backorder':'backorder'}.get(availability)
        seller = offer.get('seller')
        seller = seller.get('name') if isinstance(seller,dict) else None
        return Observation(price,stock,seller if isinstance(seller,str) else None,_shipping(offer,currency))
    amounts=set()
    currencies=set()
    for key in ('product:price:amount','og:price:amount','price','product:price'):
        amounts.update(to_decimal(v) for v in parser.values.get(key,()))
    for key in ('product:price:currency','og:price:currency','pricecurrency'):
        currencies.update(v.upper() for v in parser.values.get(key,()))
    if len(amounts)!=1 or currencies!={currency}:
        raise ValueError('Unique machine-readable price and explicit currency required')
    return Observation(Price(amounts.pop(),currency,'Unique explicit price metadata'))

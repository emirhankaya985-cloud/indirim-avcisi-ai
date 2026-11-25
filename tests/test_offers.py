from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock
import json

from tracker.offers import extract_observation
from tracker.engine import execute

NOW=datetime(2026,11,26,6,tzinfo=timezone.utc)
P={'id':'test_offer','name':'Fixture','url':'https://www.trendyol.com/fixture-p-1'}

def page(availability='InStock', price=100, currency='TRY', **extra):
    offer={'@type':'Offer','price':price,'priceCurrency':currency,
           'availability':'https://schema.org/'+availability, **extra}
    data={'@type':'Product','offers':offer}
    return '<script type="application/ld+json">'+json.dumps(data)+'</script>'


class StrictOfferTests(TestCase):
    def test_missing_currency_rejected(self):
        with self.assertRaises(ValueError):
            extract_observation('<meta property="product:price:amount" content="100">')

    def test_ambiguous_prices_rejected(self):
        with self.assertRaises(ValueError):
            extract_observation('<meta property="product:price:amount" content="100"><meta property="product:price:amount" content="200"><meta property="product:price:currency" content="TRY">')
        with self.assertRaises(ValueError):
            extract_observation(page(**{'@type':'AggregateOffer'}))

    def test_explicit_stock_seller_and_shipping(self):
        o=extract_observation(page(seller={'name':'Fixture Seller'},shippingDetails={
            'shippingDestination':{'addressCountry':'TR'},'shippingRate':{'currency':'TRY','value':0}}))
        self.assertEqual(o.stock,'in_stock')
        self.assertEqual(o.seller,'Fixture Seller')
        self.assertEqual(o.shipping,Decimal('0.00'))

    def test_conditional_shipping_unknown(self):
        o=extract_observation(page(shippingDetails={'shippingDestination':{'addressCountry':'TR','postalCode':'12345'},
                                                   'shippingRate':{'currency':'TRY','value':0}}))
        self.assertIsNone(o.shipping)

    def test_restock_only_after_explicit_out_of_stock(self):
        d=Mock()
        d.read.return_value=page('OutOfStock').encode()
        state, first=execute({'products':[P]}, {},downloader=d,current_time=NOW,dry_run=True,strict=True)
        self.assertFalse(state.get('pending'))
        d.read.return_value=page().encode()
        state, second=execute({'products':[P]},state,downloader=d,current_time=NOW+timedelta(minutes=30),dry_run=True,strict=True)
        self.assertEqual(second['restocks'],1)
        self.assertEqual(state['pending'][0]['type'],'restock')
        state, third=execute({'products':[P]},state,downloader=d,current_time=NOW+timedelta(hours=1),dry_run=True,strict=True)
        self.assertEqual(len(state['pending']),1)

    def test_out_of_stock_drop_not_alerted(self):
        d=Mock()
        d.read.return_value=page(price=100).encode()
        state,_=execute({'products':[P]}, {},downloader=d,current_time=NOW,dry_run=True,strict=True)
        d.read.return_value=page('OutOfStock',price=50).encode()
        state,counts=execute({'products':[P]},state,downloader=d,current_time=NOW+timedelta(hours=1),dry_run=True,strict=True)
        self.assertEqual(counts['price_alerts'],0)
        self.assertFalse(state.get('pending'))

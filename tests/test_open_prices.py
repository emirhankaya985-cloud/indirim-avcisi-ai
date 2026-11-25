from datetime import date,timedelta
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock,patch
import json

from scripts.import_open_prices import normalize,fetch
from scripts import live_connection_test

TODAY=date(2026,11,26)
def fixture(**changes):
    row={'id':1,'product_code':'4006381333931','location_id':2,'proof_id':3,
         'date':TODAY.isoformat(),'price':'12.50','price_per':None,'currency':'TRY',
         'price_is_discounted':False,'product_name':'Test fixture only',
         'location':{'osm_name':'Fixture shop','osm_address_country_code':'tr'}}
    row.update(changes)
    return row


class OpenPricesTests(TestCase):
    def test_dated_observation_preserves_source_id_and_date(self):
        row=normalize(fixture(),TODAY)
        self.assertEqual(row[0],1)
        self.assertEqual(row[4],TODAY)
        self.assertEqual(row[5],Decimal('12.50'))
        self.assertTrue(row[-1].endswith('/1'))

    def test_reject_unverified_and_stale(self):
        for changes in [{'product_code':'4006381333932'},{'proof_id':None},
                        {'price':'NaN'},{'currency':'USD'},{'price_per':'KILOGRAM'},
                        {'date':(TODAY-timedelta(days=91)).isoformat()},
                        {'date':(TODAY+timedelta(days=1)).isoformat()},
                        {'price_is_discounted':None}]:
            self.assertIsNone(normalize(fixture(**changes),TODAY),changes)

    def test_source_query_bounded_and_robots_checked(self):
        d=Mock()
        d.read.return_value=json.dumps({'items':[fixture(),fixture(proof_id=None)],'total':2}).encode()
        rows,returned,total=fetch(TODAY,d)
        self.assertEqual((len(rows),returned,total),(1,2,2))
        url,hosts=d.read.call_args.args
        self.assertIn('currency=TRY',url)
        self.assertIn('size=100',url)
        self.assertTrue(d.read.call_args.kwargs['respect_robots'])
        self.assertEqual(hosts,['prices.openfoodfacts.org'])

    @patch('scripts.live_connection_test.sender')
    @patch('scripts.live_connection_test.is_neon_enabled',return_value=False)
    def test_missing_db_never_sends(self,enabled,sender):
        self.assertEqual(live_connection_test.main(),2)
        sender.assert_not_called()

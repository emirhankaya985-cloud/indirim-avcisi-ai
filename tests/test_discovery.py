from datetime import datetime, timezone, timedelta
from unittest import TestCase
from unittest.mock import Mock
import json

from tracker.discovery import discover, due, batch_products
from tracker.production import tick
from tracker.engine import dispatch_pending

NOW = datetime(2026,11,26,6,tzinfo=timezone.utc)
SOURCE = {'url':'https://example.org/catalog.json','format':'catalog-json-v1',
          'authorized':True,'product_page_access_authorized':True,
          'history_storage_authorized':True,'permission_reference':'test fixture'}
ITEM = {'name':'Fixture phone','category':'telefon','url':'https://www.trendyol.com/fixture-p-1'}


class DiscoveryTests(TestCase):
    def test_permission_required_before_network(self):
        d = Mock()
        added, errors = discover({}, [dict(SOURCE, authorized=False)], d, NOW)
        self.assertEqual(added, 0)
        self.assertTrue(errors)
        d.read.assert_not_called()

    def test_dedup_and_reject_invalid_catalog_items(self):
        d = Mock()
        d.read.return_value = json.dumps([ITEM, ITEM, dict(ITEM, url='https://evil.org/a'),
                                          dict(ITEM, category='invalid',url='https://www.n11.com/x')]).encode()
        state = {}
        self.assertEqual(discover(state,[SOURCE],d,NOW)[0], 1)
        self.assertEqual(discover(state,[SOURCE],d,NOW)[0], 0)
        self.assertEqual(len(state['catalog']), 1)

    def test_rotation(self):
        state={'catalog':{str(i):dict(ITEM,id=str(i),url=ITEM['url']+str(i)) for i in range(20)}}
        a=batch_products(state,[],10)
        b=batch_products(state,[],10)
        self.assertEqual(len(set(p['id'] for p in a+b)),20)

    def test_intervals(self):
        self.assertFalse(due(NOW.isoformat(),NOW+timedelta(hours=1),2))
        self.assertTrue(due(NOW.isoformat(),NOW+timedelta(hours=2),2))
        self.assertFalse(due(NOW.isoformat(),NOW+timedelta(hours=2),3))

    def test_revoked_source_not_scanned(self):
        state={'catalog':{'a':dict(ITEM,id='a',source=SOURCE['url'])}}
        d=Mock()
        _,counts=tick({},state,d,NOW)
        self.assertEqual(counts['products_attempted'],0)
        d.read.assert_not_called()

    def test_primary_channel_receipt_not_telegram(self):
        state={'pending':[{'id':'one','body':'fixture'}]}
        self.assertEqual(dispatch_pending(state,lambda _: (True,'ntfy:test-id'),NOW),(1,0))
        self.assertEqual(state['delivery_log'][0]['channel'],'ntfy')
        self.assertEqual(state['delivery_log'][0]['message_id'],'test-id')
        self.assertNotIn('telegram_message_id',state['delivery_log'][0])

    def test_discovery_and_scan_baseline_no_alert(self):
        d=Mock()
        d.read.side_effect=[json.dumps([ITEM]).encode(),
                            b'<meta property="product:price:amount" content="100"><meta property="product:price:currency" content="TRY">']
        state,counts=tick({'catalog_sources':[SOURCE]}, {},d,NOW)
        self.assertEqual(counts['discovered'],1)
        self.assertEqual(counts['products_ok'],1)
        self.assertEqual(counts['price_alerts'],0)
        self.assertFalse(state.get('pending'))

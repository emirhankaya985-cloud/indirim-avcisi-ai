"""Regression checks for observed prices and resilient notifications."""
from datetime import datetime, timezone
from unittest import TestCase

from tracker.engine import dispatch_pending, execute

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
PRODUCT = {
    'id': 'test_keyboard',
    'name': 'Test Keyboard',
    'url': 'https://www.trendyol.com/keyboard/sample-product-p-123',
    'currency': 'TRY',
    'drop_percent': 5,
}


class _Downloader:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error

    def read(self, url, hosts, respect_robots=True):
        if self.error:
            raise self.error
        return self.data


class ProductionRegressionTests(TestCase):
    def test_price_record_preserves_public_source_url(self):
        html = b'<meta property="product:price:amount" content="1200"><meta property="product:price:currency" content="TRY">'
        state, summary = execute({'products': [PRODUCT]}, {}, downloader=_Downloader(html),
                                 sender=lambda _: (True, '15'), current_time=NOW)
        self.assertEqual(summary['products_ok'], 1)
        self.assertEqual(summary['sent'], 0)
        self.assertIn(PRODUCT['url'], state['products'][PRODUCT['id']]['evidence'])
        self.assertEqual(state['products'][PRODUCT['id']]['samples'][0]['price'], '1200.00')

    def test_failure_does_not_insert_fake_price(self):
        state, summary = execute({'products': [PRODUCT]}, {},
                                 downloader=_Downloader(error=PermissionError('Robots disallows')),
                                 current_time=NOW)
        self.assertEqual(summary['products_ok'], 0)
        self.assertEqual(len(summary['errors']), 1)
        self.assertNotIn('samples', state['products'][PRODUCT['id']])
        self.assertNotIn('last_successful_price_scan', state)

    def test_sender_exception_preserves_pending_and_backoff(self):
        state = {'pending': [{'id': 'a', 'body': 'price drop', 'attempts': 0}]}
        def broken_sender(_):
            raise TimeoutError('sensitive request details must not be logged')
        sent, failed = dispatch_pending(state, sender=broken_sender, current_time=NOW)
        self.assertEqual((sent, failed), (0, 1))
        self.assertEqual(len(state['pending']), 1)
        self.assertEqual(state['pending'][0]['attempts'], 1)
        self.assertIn('TimeoutError', state['pending'][0]['last_error'])
        self.assertNotIn('sensitive request details', state['pending'][0]['last_error'])
        self.assertEqual(state.get('delivery_log'), [])

    def test_repeated_scan_does_not_create_alert_without_price_change(self):
        html = b'<meta property="product:price:amount" content="1000">'
        d = _Downloader(html)
        original, _ = execute({'products': [PRODUCT]}, {}, downloader=d, current_time=NOW)
        again, summary = execute({'products': [PRODUCT]}, original, downloader=d, current_time=NOW)
        self.assertEqual(summary['price_alerts'], 0)
        self.assertEqual(summary['sent'], 0)
        self.assertEqual(again.get('pending'), original.get('pending'))

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tracker.engine import update_price, update_feed, execute, dispatch_pending
from tracker.network import validate_url


NOW = datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc)
PRODUCT = {'id': 'kb01', 'name': 'Klavye', 'url': 'https://www.trendyol.com/real/product-123',
           'currency': 'TRY', 'drop_percent': 5, 'cooldown_hours': 24}


class FakeDownloader:
    def __init__(self, contents):
        self.contents = contents
        self.calls = []

    def read(self, url, hosts, respect_robots=True):
        self.calls.append((url, hosts, respect_robots))
        return self.contents[url]


class EngineTests(unittest.TestCase):
    def test_first_read_baseline_no_spam(self):
        state = {}
        self.assertFalse(update_price(state, PRODUCT, Decimal('100.00'), NOW, 'Test'))
        self.assertFalse(state.get('pending'))
        self.assertEqual(state['products']['kb01']['last_price'], '100.00')

    def test_real_drop_creates_one_pending_alert(self):
        state = {}
        update_price(state, PRODUCT, Decimal('100.00'), NOW, 'Test')
        self.assertTrue(update_price(state, PRODUCT, Decimal('90.00'), NOW+timedelta(hours=1), 'Test'))
        self.assertEqual(len(state['pending']), 1)
        self.assertIn('90.00', state['pending'][0]['body'])
        self.assertFalse(update_price(state, PRODUCT, Decimal('90.00'), NOW+timedelta(hours=2), 'Test'))
        self.assertEqual(len(state['pending']), 1)

    def test_fake_deal_prevented_by_30day_low(self):
        state = {}
        update_price(state, PRODUCT, Decimal('100.00'), NOW, 'Test')
        update_price(state, PRODUCT, Decimal('80.00'), NOW+timedelta(hours=1), 'Test')
        update_price(state, PRODUCT, Decimal('110.00'), NOW+timedelta(hours=26), 'Test')
        self.assertFalse(update_price(state, PRODUCT, Decimal('90.00'), NOW+timedelta(hours=27), 'Test'))
        self.assertEqual(len(state['pending']), 1)

    def test_telegram_retries_and_ack(self):
        state = {'pending': [{'id':'a', 'body': 'hello', 'attempts':0}]}
        ok, failed = dispatch_pending(state, sender=lambda body: (False, 'No token'), current_time=NOW)
        self.assertEqual((ok, failed), (0, 1))
        self.assertEqual(len(state['pending']), 1)
        ok, failed = dispatch_pending(state, sender=lambda body: (True, '12345'), current_time=NOW+timedelta(minutes=30))
        self.assertEqual((ok, failed), (1, 0))
        self.assertEqual(len(state['pending']), 0)
        self.assertEqual(state['delivery_log'][-1]['telegram_message_id'], '12345')

    def test_feed_initial_is_baseline_then_notifies_once(self):
        state = {}
        feed = {'id': 'test-rss', 'name': 'Official Feed', 'url': 'https://example.com/feed.xml'}
        old = [{'id':'old','title':'Coupon old','link':'https://example.com/o'}]
        new = [{'id':'new','title':'Coupon new','link':'https://example.com/n'}]
        self.assertEqual(update_feed(state, feed, old, NOW), 0)
        self.assertEqual(update_feed(state, feed, old+new, NOW+timedelta(hours=1)), 1)
        self.assertEqual(update_feed(state, feed, old+new, NOW+timedelta(hours=2)), 0)
        self.assertIn('DOĞRULANMADI', state['pending'][0]['body'])

    def test_url_whitelist(self):
        self.assertEqual(validate_url(PRODUCT['url'], ['trendyol.com']), PRODUCT['url'])
        for url in ('http://www.trendyol.com/a', 'https://trendyol.com.evil.org/a',
                    'https://127.0.0.1/a', 'https://admin:secret@trendyol.com/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url, ['trendyol.com'])

    def test_end_to_end_with_mock_price(self):
        html = b'''<script type="application/ld+json">{"@type":"Product","offers":
        {"@type":"Offer","price":"100","priceCurrency":"TRY"}}</script>'''
        d = FakeDownloader({PRODUCT['url']: html})
        out, count = execute({'products':[PRODUCT]}, {}, downloader=d, sender=lambda x: (True,'3'), current_time=NOW)
        self.assertEqual(count['products_ok'], 1)
        self.assertEqual(count['sent'], 0)
        self.assertEqual(out['products']['kb01']['last_price'], '100.00')
        self.assertTrue(d.calls[0][2])

    def test_backoff_prevents_repeated_send_each_scan(self):
        state = {'pending': [{'id': 'x', 'body': 'hello', 'attempts': 0}]}
        calls = []
        def fail(body):
            calls.append(body)
            return False, 'transient'
        self.assertEqual(dispatch_pending(state, sender=fail, current_time=NOW), (0, 1))
        self.assertEqual(dispatch_pending(state, sender=fail, current_time=NOW+timedelta(minutes=5)), (0, 0))
        self.assertEqual(len(calls), 1)
        self.assertEqual(state['pending'][0]['next_attempt_at'], (NOW+timedelta(minutes=30)).isoformat(timespec='seconds'))
        self.assertEqual(dispatch_pending(state, sender=fail, current_time=NOW+timedelta(minutes=30)), (0, 1))
        self.assertEqual(len(calls), 2)
        self.assertEqual(state['pending'][0]['next_attempt_at'], (NOW+timedelta(minutes=90)).isoformat(timespec='seconds'))

    def test_duplicate_coupon_items_only_alert_once(self):
        feed = {'id':'feed1','name':'Coupon Feed','url':'https://example.com/rss'}
        state = {}
        update_feed(state, feed, [{'id':'old', 'title':'a', 'link':''}], NOW)
        duplicated = [{'id':'sale', 'title':'coupon sale', 'link':'https://example.com/sale'}] * 2
        self.assertEqual(update_feed(state, feed, duplicated, NOW+timedelta(minutes=30)), 1)
        self.assertEqual(len(state['pending']), 1)

    def test_fake_public_coupon_host_rejected(self):
        from tracker.engine import _validate_entries
        for host in ('localhost', 'printer.local', 'intranet', '127.0.0.1', 'host.internal'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                _validate_entries({'coupon_feeds': [{'id':'abc', 'name':'feed', 'url':f'https://{host}/rss'}]})

    def test_execution_audit_log_and_recovery(self):
        html = b'<meta property="product:price:amount" content="99.99"><meta property="product:price:currency" content="TRY">'
        d = FakeDownloader({PRODUCT['url']: html})
        out, count = execute({'products':[PRODUCT]}, {}, downloader=d, sender=lambda x: (True,'3'), current_time=NOW)
        self.assertEqual(out['run_log'][0]['products_ok'], 1)
        self.assertEqual(out['last_run'], NOW.isoformat(timespec='seconds'))
        self.assertFalse(out['run_log'][0]['errors'])
        self.assertEqual(count['products_ok'], 1)

    def test_same_alert_not_repeated_with_cooldown(self):
        state = {}
        update_price(state, PRODUCT, Decimal('100'), NOW, 'Test')
        update_price(state, PRODUCT, Decimal('95'), NOW+timedelta(hours=1), 'Test')
        self.assertFalse(update_price(state, PRODUCT, Decimal('80'), NOW+timedelta(hours=2), 'Test'))
        self.assertEqual(len(state['pending']), 1)

    def test_dry_run_does_not_call_sender(self):
        html = b'<meta property="product:price:amount" content="100">'
        d = FakeDownloader({PRODUCT['url']: html})
        sent = []
        out, counts = execute({'products':[PRODUCT]}, {}, downloader=d,
                              sender=lambda body: sent.append(body) or (True, '1'),
                              dry_run=True, current_time=NOW)
        self.assertEqual(sent, [])
        self.assertEqual(counts['products_ok'], 1)

    def test_state_file_persistence_round_trip(self):
        import tempfile
        from pathlib import Path
        from tracker.engine import save_json, read_json
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'store' / 'state.json'
            record = {'products': {'one': {'last_price': '149.90'}}, 'pending': []}
            save_json(dest, record)
            self.assertTrue(dest.exists())
            self.assertEqual(read_json(dest, {})['products']['one']['last_price'], '149.90')

    def test_telegram_without_secrets_does_not_fake_a_send(self):
        from unittest.mock import patch
        from tracker.telegram import send_message
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': ''}):
            ok, detail = send_message('test')
        self.assertFalse(ok)
        self.assertIn('missing', detail)

    def test_no_configuration_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, 'At least one'):
            execute({'products':[], 'coupon_feeds':[]}, {})


if __name__ == '__main__':
    unittest.main()

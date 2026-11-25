import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from tracker.daily_report import render, send_ntfy


class DailyReportTests(unittest.TestCase):
    now = datetime(2026, 11, 26, 6, tzinfo=timezone.utc)
    config = {'products': [{}], 'coupon_feeds': [{}]}

    def test_blocked_without_database(self):
        body = render({}, self.config, True, self.now, False)
        self.assertIn('ENGELLİ', body)
        self.assertIn('Bekleyen alarm: bilinmiyor', body)

    def test_no_runs_is_not_success(self):
        self.assertIn('VERİ YOK', render({}, self.config, True, self.now, True))

    def test_rolling_window_and_errors(self):
        state = {'run_log': [
            {'time': (self.now - timedelta(hours=25)).isoformat(), 'products_ok': 99},
            {'time': self.now.isoformat(), 'products_ok': 1, 'feeds_ok': 1,
             'sent': 1, 'errors': ['private details']},
            {'time': 'invalid'},
        ]}
        body = render(state, self.config, True, self.now, True)
        self.assertIn('KONTROL GEREKLİ', body)
        self.assertIn('Başarılı ürün okumaları: 1', body)
        self.assertNotIn('private details', body)
        self.assertIn('09:00 Türkiye', body)

    def test_disabled_and_empty_config(self):
        self.assertIn('ENGELLİ', render({}, self.config, False, self.now, True))
        self.assertIn('ENGELLİ', render({}, {}, True, self.now, True))

    @patch('tracker.daily_report.build_opener')
    def test_ntfy_missing_or_invalid_topic_no_request(self, opener):
        self.assertFalse(send_ntfy('test', {})[0])
        self.assertFalse(send_ntfy('test', {'NTFY_TOPIC': '../unsafe'})[0])
        opener.assert_not_called()

    @patch('tracker.daily_report.build_opener')
    def test_ntfy_requires_acknowledgement(self, opener):
        response = MagicMock()
        opener.return_value.open.return_value.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"event":"message","id":"test-id"}'
        self.assertTrue(send_ntfy('test', {'NTFY_TOPIC': 'example-test-123456'})[0])
        response.read.return_value = b'{"event":"message"}'
        self.assertFalse(send_ntfy('test', {'NTFY_TOPIC': 'example-test-123456'})[0])
        opener.return_value.open.side_effect = TimeoutError()
        self.assertFalse(send_ntfy('test', {'NTFY_TOPIC': 'example-test-123456'})[0])


if __name__ == '__main__':
    unittest.main()

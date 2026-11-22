"""Configuration tests prevent misleading green scheduled runs."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.preflight import problems


EXAMPLE_PRODUCT = {
    'id': 'approved_01', 'name': 'Approved product',
    'url': 'https://www.trendyol.com/test/sample-p-12345',
    'currency': 'TRY', 'drop_percent': 5,
}
VALID_SECRETS = {
    'TRACKING_ENABLED': 'true',
    'NEON_DATABASE_URL': 'placeholder-do-not-connect',
    'TELEGRAM_BOT_TOKEN': 'placeholder-do-not-connect',
    'TELEGRAM_CHAT_ID': 'placeholder-do-not-connect',
}


class PreflightTests(TestCase):
    def check(self, config, env):
        with TemporaryDirectory() as folder:
            p = Path(folder) / 'config.json'
            if config is not None:
                p.write_text(json.dumps(config), encoding='utf-8')
            return problems(p, env)

    def test_all_config_present(self):
        self.assertEqual([], self.check({'products': [EXAMPLE_PRODUCT], 'coupon_feeds': []}, VALID_SECRETS))

    def test_missing_variable_blocks_job(self):
        env = {k: v for k, v in VALID_SECRETS.items() if k != 'TRACKING_ENABLED'}
        self.assertIn('TRACKING_ENABLED', ' '.join(self.check({'products': [EXAMPLE_PRODUCT]}, env)))

    def test_wrong_variable_value_blocks_job(self):
        env = {**VALID_SECRETS, 'TRACKING_ENABLED': 'TRUE'}
        self.assertIn('TRACKING_ENABLED', ' '.join(self.check({'products': [EXAMPLE_PRODUCT]}, env)))

    def test_missing_secrets_all_reported(self):
        issues = self.check({'products': [EXAMPLE_PRODUCT]}, {'TRACKING_ENABLED': 'true'})
        for key in ('NEON_DATABASE_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            self.assertIn(key, ' '.join(issues))

    def test_empty_products_blocked(self):
        self.assertIn('zero user-approved products', ' '.join(self.check({'products': [], 'coupon_feeds': []}, VALID_SECRETS)))

    def test_coupon_only_not_misreported_as_product_tracking(self):
        cfg = {'products': [], 'coupon_feeds': [{'id': 'feed', 'name': 'Example', 'url': 'https://www.example.com/rss'}]}
        self.assertIn('zero user-approved products', ' '.join(self.check(cfg, VALID_SECRETS)))

    def test_invalid_json_blocked(self):
        self.assertIn('missing or invalid', ' '.join(self.check(None, VALID_SECRETS)))

    def test_invalid_url_blocked(self):
        cfg = {'products': [{**EXAMPLE_PRODUCT, 'url': 'http://127.0.0.1/path'}], 'coupon_feeds': []}
        self.assertIn('missing or invalid', ' '.join(self.check(cfg, VALID_SECRETS)))

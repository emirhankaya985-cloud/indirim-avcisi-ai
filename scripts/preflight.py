"""Check production prerequisites without exposing secret values.

Exit 2 means configuration blocked; no product URL is fetched, no DB written,
and no Telegram message attempted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from tracker.engine import _validate_entries

REQUIRED_SECRETS = ('NEON_DATABASE_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')


def problems(config_path: Path, env: Mapping[str, str]) -> list[str]:
    issues = []
    if env.get('TRACKING_ENABLED') != 'true':
        issues.append('TRACKING_ENABLED repository variable must equal true')
    for key in REQUIRED_SECRETS:
        if not env.get(key, '').strip():
            issues.append(f'{key} repository secret is missing')
    try:
        with config_path.open(encoding='utf-8') as source:
            config = json.load(source)
        if not isinstance(config, dict):
            raise ValueError('configuration must be a JSON object')
        if not config.get('products'):
            issues.append('config.json has zero user-approved products')
        if config.get('products') or config.get('coupon_feeds'):
            _validate_entries(config)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        issues.append('config.json is missing or invalid (no safe live scan possible)')
    return list(dict.fromkeys(issues))


def main() -> int:
    issues = problems(Path('config.json'), os.environ)
    summary = Path(os.environ['GITHUB_STEP_SUMMARY']) if os.environ.get('GITHUB_STEP_SUMMARY') else None
    if issues:
        lines = ['## Production blocked: missing configuration',
                 'No live product scan or Telegram send attempted.',
                 *[f'- {message}' for message in issues]]
        if summary:
            with summary.open('a', encoding='utf-8') as output:
                output.write('\n'.join(lines) + '\n')
        for message in issues:
            print(f'::error::{message}')
        return 2
    if summary:
        with summary.open('a', encoding='utf-8') as output:
            output.write('## Production prerequisites present\n')
    print('Production prerequisites present (not proof of working live connections)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

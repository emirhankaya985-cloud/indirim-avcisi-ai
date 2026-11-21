from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

from .engine import execute, read_json
from .storage import load, persist, is_neon_enabled
from .telegram import send_message


def main() -> int:
    parser = argparse.ArgumentParser(description='Price and coupon candidate tracking')
    parser.add_argument('command', choices=['run', 'status', 'test-telegram'])
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--state', default='data/state.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.command == 'test-telegram':
        ok, msg = send_message('✅ İndirim Avcısı AI - Telegram bağlantı testi')
        print(f'Telegram OK: message_id={msg}' if ok else f'Telegram FAILED: {msg}')
        return 0 if ok else 1
    state_path = Path(args.state)
    try:
        current, version = load(state_path)
    except RuntimeError as exc:
        print(f'STORAGE ERROR: {exc}', file=sys.stderr)
        return 2
    if args.command == 'status':
        print(json.dumps({'last_run': current.get('last_run'),
                          'last_successful_price_scan': current.get('last_successful_price_scan'),
                          'storage_backend': 'neon' if is_neon_enabled() else 'git-json',
                          'last_summary': current.get('last_summary'),
                          'pending': len(current.get('pending', [])),
                          'tracked_products': len(current.get('products', {})),
                          'recent_runs': current.get('run_log', [])[-5:]}, ensure_ascii=False, indent=2))
        return 0
    try:
        config = read_json(Path(args.config), {})
        future, counts = execute(config, current, dry_run=args.dry_run)
        print(json.dumps(counts, indent=2, ensure_ascii=False))
        if not args.dry_run:
            persist(state_path, future, version)
        return 1 if counts['errors'] else 0
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
        print(f'CONFIG/STATE ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

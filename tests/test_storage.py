"""Persistence boundary tests: no hidden fallback, compare-and-swap and history."""
from __future__ import annotations

from pathlib import Path
import json
import os
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tracker import storage


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.rowcount = 1
        self.sql = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.sql.append((sql, params))
    def fetchone(self): return self.row


class _Connection:
    def __init__(self, row): self.cursor_obj = _Cursor(row)
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self.cursor_obj


class StorageTests(TestCase):
    def test_file_roundtrip_without_neon(self):
        with patch.dict(os.environ, {'NEON_DATABASE_URL': ''}), TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            state, version = storage.load(path)
            self.assertEqual(version, None)
            self.assertEqual(state['products'], {})
            state['products']['sample'] = {'last_price': '11.00'}
            storage.persist(path, state, version)
            self.assertEqual(json.loads(path.read_text())['products']['sample']['last_price'], '11.00')

    def test_neon_load_does_not_use_local_state(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {'NEON_DATABASE_URL': 'postgres://not-a-secret'}):
            local = Path(d) / 'state.json'
            local.write_text('{"products":{"wrong":{}}}')
            conn = _Connection(({'products': {'right': {}}, 'pending': []}, 7))
            with patch.object(storage, '_connection', return_value=conn):
                data, version = storage.load(local)
            self.assertEqual(version, 7)
            self.assertIn('right', data['products'])
            self.assertNotIn('wrong', data['products'])

    def test_neon_write_checks_version_and_inserts_history(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {'NEON_DATABASE_URL': 'postgres://not-a-secret'}):
            conn = _Connection(None)
            data = {'products': {'one': {'samples': [{'time': '2026-11-21T19:00:00+00:00', 'price': '99.99'}],
                                         'currency': 'TRY', 'evidence': 'Product JSON-LD'}}}
            with patch.object(storage, '_connection', return_value=conn):
                storage.persist(Path(d) / 'not-written.json', data, 7)
            self.assertEqual(len(conn.cursor_obj.sql), 2)
            self.assertEqual(conn.cursor_obj.sql[0][1][1], 7)
            self.assertEqual(conn.cursor_obj.sql[1][1][0], 'one')
            self.assertFalse((Path(d) / 'not-written.json').exists())

    def test_neon_conflict_refuses_local_fallback(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {'NEON_DATABASE_URL': 'postgres://not-a-secret'}):
            conn = _Connection(None)
            conn.cursor_obj.rowcount = 0
            local = Path(d) / 'state.json'
            with patch.object(storage, '_connection', return_value=conn):
                with self.assertRaisesRegex(RuntimeError, 'version conflict'):
                    storage.persist(local, {'products': {}}, 99)
            self.assertFalse(local.exists())

    def test_neon_not_configured_is_opt_in(self):
        with patch.dict(os.environ, {'NEON_DATABASE_URL': ''}):
            self.assertFalse(storage.is_neon_enabled())

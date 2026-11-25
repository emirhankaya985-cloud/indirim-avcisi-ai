"""Optional Neon PostgreSQL persistence. Never silently fall back when configured.

The single JSONB row is the authoritative state; append-only price_history
provides independent SQL-queryable observations. Optimistic versioning avoids
silently overwriting concurrent updates.
"""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json
import os

from .engine import read_json, save_json


EMPTY = {'products': {}, 'feeds': {}, 'pending': [], 'delivery_log': [], 'run_log': []}


def is_neon_enabled() -> bool:
    return bool(os.environ.get('NEON_DATABASE_URL', '').strip())


def _connection():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('Neon driver missing: pip install -r requirements.txt') from exc
    try:
        return psycopg.connect(os.environ['NEON_DATABASE_URL'], connect_timeout=10, sslmode='require')
    except Exception as exc:
        # Do not include connection strings or secret-bearing driver messages.
        raise RuntimeError(f'Neon connection unavailable ({type(exc).__name__})') from None


def load(path: Path) -> tuple[dict, int | None]:
    if not is_neon_enabled():
        return read_json(path, EMPTY), None
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT payload, version FROM tracker_state WHERE id = 1')
            result = cur.fetchone()
            if result is None:
                raise RuntimeError('Neon state row has not been initialized')
            state, version = result
            if isinstance(state, str):
                state = json.loads(state)
            if not isinstance(state, dict):
                raise RuntimeError('Invalid Neon state payload')
            return state, int(version)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Neon read failed ({type(exc).__name__})') from None


def persist(path: Path, state: dict, expected_version: int | None) -> None:
    if not is_neon_enabled():
        save_json(path, state)
        return
    if expected_version is None:
        raise RuntimeError('Neon state version missing')
    snapshot = deepcopy(state)
    observations = []
    for product_id, product_state in snapshot.get('products', {}).items():
        for sample in product_state.get('samples', []):
            if sample.get('_history_saved') is True:
                continue
            observations.append((product_id, sample['time'], sample['price'],
                                 sample.get('currency', product_state.get('currency', 'TRY')),
                                 sample.get('evidence', 'legacy: individual source evidence unavailable')))
            sample['_history_saved'] = True
    try:
        with _connection() as conn, conn.cursor() as cur:
            # PostgreSQL transaction: the state and its normalized price history
            # commit together, or neither is persisted.
            cur.execute(
                'UPDATE tracker_state SET payload = %s::jsonb, version = version + 1, '
                'updated_at = now() WHERE id = 1 AND version = %s',
                (json.dumps(snapshot, ensure_ascii=False), expected_version),
            )
            if cur.rowcount != 1:
                raise RuntimeError('Neon state version conflict; refusing overwrite')
            for observation in observations:
                cur.execute(
                    'INSERT INTO price_history (product_id, observed_at, price, currency, evidence) '
                    'VALUES (%s, %s, %s, %s, %s) ON CONFLICT (product_id, observed_at) DO NOTHING',
                    observation,
                )
        # Update caller only after the transaction committed successfully.
        state.clear()
        state.update(snapshot)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Neon write failed ({type(exc).__name__})') from None

"""NWG-only Alliance Intel reader. Uses the existing DS database login, never the browser.

No scheduled polling, new secrets, storage writes, player UIDs or Groq data transfers.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

TTL_SECONDS = 1800
MAX_DAILY_READS = 48
MAX_RESPONSE_BYTES = 131072
MAX_PLAYERS = 200
SQL = "select lw_ds_private.nwg_alliance_snapshot()"


class AllianceReadError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def error_code(exc):
    """Only return a stable code; errors may contain the secret DSN."""
    if isinstance(exc, AllianceReadError):
        return exc.code
    state = str(getattr(exc, 'sqlstate', '') or '')
    if state in ('42501',):
        return 'ALLIANCE-PERMISSION'
    if state in ('42883', '42P01', '3F000', '42703'):
        return 'ALLIANCE-SETUP'
    if state in ('28P01', '28000'):
        return 'ALLIANCE-AUTH'
    if state in ('57014',):
        return 'ALLIANCE-TIMEOUT'
    if state.startswith('08'):
        return 'ALLIANCE-NETWORK'
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return 'ALLIANCE-NETWORK'
    return 'ALLIANCE-UNAVAILABLE'


def validate_snapshot(value):
    if not isinstance(value, dict) or value.get('source') not in ('roster', 'identities'):
        raise AllianceReadError('ALLIANCE-INVALID-RESPONSE')
    players = value.get('players')
    if (not isinstance(players, list) or len(players) > MAX_PLAYERS
            or any(not isinstance(item, dict) for item in players)):
        raise AllianceReadError('ALLIANCE-INVALID-RESPONSE')
    if not isinstance(value.get('snapshot_at'), (str, type(None))):
        raise AllianceReadError('ALLIANCE-INVALID-RESPONSE')
    if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise AllianceReadError('ALLIANCE-TOO-LARGE')
    return value


def normalize_members(snapshot):
    """Whitelisted display fields only: never retain or render player UIDs."""
    from core import FIELDS, safe_text
    result = []
    for item in validate_snapshot(snapshot)['players']:
        row = {field: safe_text(item.get(field), 96 if field == 'Jogador' else 120)
               for field in FIELDS}
        if row['Jogador'] and row['Jogador'] != '—':
            result.append(row)
    return result


class AllianceReader:
    """Shared 30-minute cache and 48-read/day guard, per Streamlit process."""
    def __init__(self, dsn, connector=None, ca_loader=None, *, clock=None, utc_now=None):
        parsed = urlparse(dsn)
        if (parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname
                or not re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com', parsed.hostname)
                or not re.fullmatch(r'lw_ds_streamlit_reader\.[a-z0-9]+', parsed.username or '')
                or not parsed.password or parsed.port != 5432 or parsed.path != '/postgres'
                or parsed.query or parsed.fragment):
            raise AllianceReadError('ALLIANCE-CONFIG')
        self.dsn = dsn
        self.connector = connector
        self.ca_loader = ca_loader
        self.clock = clock or time.monotonic
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.day = None
        self.attempts = 0
        self.until = 0.0
        self.cached = None
        self.status = 'empty'
        self.reason = ''
        self.synced_at = ''

    def _fetch(self):
        connector = self.connector
        if connector is None:
            import psycopg
            connector = psycopg.connect
        ca_loader = self.ca_loader
        if ca_loader is None:
            from ds_web import supabase_ca_pem
            ca_loader = supabase_ca_pem
        with tempfile.TemporaryDirectory(prefix='nwg-ca-') as folder:
            ca_path = Path(folder) / 'supabase-ca.crt'
            ca_path.write_bytes(ca_loader())
            with connector(self.dsn, sslmode='verify-full', sslrootcert=str(ca_path),
                           connect_timeout=8, autocommit=True, prepare_threshold=None) as conn:
                with conn.cursor() as cur:
                    cur.execute("set statement_timeout='8s'")
                    cur.execute(SQL)
                    row = cur.fetchone()
        return row[0] if row else None

    def read(self):
        with self.lock:
            now = self.utc_now().astimezone(timezone.utc)
            if self.day != now.date():
                self.day = now.date()
                self.attempts = 0
            if self.clock() < self.until:
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise AllianceReadError(self.reason or 'ALLIANCE-UNAVAILABLE')
            if self.attempts >= MAX_DAILY_READS:
                self.status = 'stale' if self.cached is not None else 'error'
                self.reason = 'ALLIANCE-DAILY-LIMIT'
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise AllianceReadError(self.reason)
            self.attempts += 1
            try:
                value = validate_snapshot(self._fetch())
                self.cached = copy.deepcopy(value)
                self.status = 'fresh'
                self.reason = ''
                self.synced_at = now.isoformat(timespec='seconds')
                return copy.deepcopy(self.cached)
            except Exception as exc:
                self.reason = error_code(exc)
                self.status = 'stale' if self.cached is not None else 'error'
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise AllianceReadError(self.reason) from None
            finally:
                # Applies to failures too: repeated browser refreshes cannot flood Supabase.
                self.until = self.clock() + TTL_SECONDS


_READER_LOCK = threading.RLock()


@lru_cache(maxsize=2)
def _reader(dsn):
    return AllianceReader(dsn)


def reader(dsn):
    with _READER_LOCK:
        return _reader(dsn)

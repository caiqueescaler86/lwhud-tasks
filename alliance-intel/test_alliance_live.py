"""Offline tests: no network, database, Streamlit, credentials or live data."""
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from alliance_live import (AllianceReader, AllianceReadError, MAX_DAILY_READS,
                           TTL_SECONDS, SQL, error_code, normalize_members,
                           validate_snapshot)

DSN = 'postgresql://lw_ds_streamlit_reader.abc:fake-password@aws-0-region.pooler.supabase.com:5432/postgres'
SAMPLE = {
    'source': 'roster', 'snapshot_at': '2026-11-27 15:00:00+00',
    'alliance': 'NWG', 'server': 1512,
    'players': [
        {'Tag': 'NWG', 'Jogador': 'Anne', 'Profissão (código)': 'Tipo 101',
         'Nível profissão': '63', 'Cargo': 'R4', 'UID': '2222430699077000'},
        {'Tag': 'NWG', 'Jogador': 'Gui', 'Profissão (código)': 'Tipo 102',
         'Nível profissão': '55', 'Cargo': 'R3'},
    ],
}


class FakeCursor:
    def __init__(self, value):
        self.value = value
        self.queries = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, q): self.queries.append(q)
    def fetchone(self): return (self.value,)


class FakeConnection:
    def __init__(self, value): self.cur = FakeCursor(value)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self.cur


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.mono = 0
        self.now = datetime(2026, 11, 27, 15, tzinfo=timezone.utc)
        self.calls = 0
        self.reader = AllianceReader(DSN, clock=lambda: self.mono,
                                     utc_now=lambda: self.now)
        def fake_fetch():
            self.calls += 1
            return SAMPLE
        self.reader._fetch = fake_fetch

    def advance(self, seconds=TTL_SECONDS):
        self.mono += seconds
        self.now += timedelta(seconds=seconds)

    def test_one_fetch_for_multiple_visitors(self):
        seen = self.reader.read()
        seen['players'].append({'Jogador': 'mutation'})
        for _ in range(100):
            self.assertEqual(self.reader.read()['players'], SAMPLE['players'])
        self.assertEqual(self.calls, 1)
        self.advance()
        self.reader.read()
        self.assertEqual(self.calls, 2)

    def test_concurrent_read_is_coalesced(self):
        errors = []
        def call():
            try: self.reader.read()
            except Exception as exc: errors.append(str(exc))
        threads = [threading.Thread(target=call) for _ in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.calls, 1)

    def test_failure_serves_last_snapshot_and_backs_off(self):
        self.reader.read()
        self.advance()
        def fail():
            self.calls += 1
            raise OSError('fake network failure with secret')
        self.reader._fetch = fail
        self.assertEqual(self.reader.read()['source'], 'roster')
        self.assertEqual(self.reader.status, 'stale')
        self.assertEqual(self.reader.reason, 'ALLIANCE-NETWORK')
        self.reader.read()
        self.assertEqual(self.calls, 2)

    def test_no_data_failure_backs_off(self):
        self.reader._fetch = lambda: None
        with self.assertRaisesRegex(AllianceReadError, 'ALLIANCE-INVALID-RESPONSE'):
            self.reader.read()
        with self.assertRaises(AllianceReadError):
            self.reader.read()
        self.assertEqual(self.reader.attempts, 1)

    def test_daily_limit_and_reset(self):
        for _ in range(MAX_DAILY_READS):
            self.reader.read()
            self.mono += TTL_SECONDS  # Hold UTC date fixed to exercise the daily cap.
        self.reader.read()
        self.assertEqual(self.calls, MAX_DAILY_READS)
        self.assertEqual(self.reader.reason, 'ALLIANCE-DAILY-LIMIT')
        self.now = datetime(2026, 11, 28, 0, tzinfo=timezone.utc)
        self.reader.read()
        self.assertEqual(self.calls, MAX_DAILY_READS + 1)

    def test_database_tls_and_fixed_query(self):
        connection = FakeConnection(SAMPLE)
        captured = {}
        def connect(dsn, **kwargs):
            captured.update(kwargs)
            self.assertEqual(dsn, DSN)
            return connection
        reader = AllianceReader(DSN, connector=connect, ca_loader=lambda: b'FAKE CA')
        self.assertEqual(reader.read()['source'], 'roster')
        self.assertEqual(captured['sslmode'], 'verify-full')
        self.assertEqual(captured['connect_timeout'], 8)
        self.assertEqual(connection.cur.queries[-1], SQL)
        self.assertNotIn('uid', SQL.lower())

    def test_redacted_error_codes(self):
        class PgError(Exception):
            sqlstate = '42501'
        self.assertEqual(error_code(PgError('secret password')), 'ALLIANCE-PERMISSION')
        self.assertEqual(error_code(ValueError('postgresql://secret')), 'ALLIANCE-UNAVAILABLE')

    def test_reject_bad_dsn_and_snapshot(self):
        with self.assertRaises(AllianceReadError):
            AllianceReader('postgresql://postgres:pw@db.example.com:5432/postgres')
        with self.assertRaises(AllianceReadError):
            validate_snapshot({'source': 'roster', 'players': [{'name': 'x'}]*201})
        with self.assertRaises(AllianceReadError):
            validate_snapshot({'source': 'all-players', 'players': []})

    def test_whitelist_removes_uid_before_ui(self):
        # The real core module provides the same safe_text / FIELDS interface.
        stub = types.ModuleType('core')
        stub.FIELDS = ('Tag', 'Jogador', 'Cargo', 'Profissão (código)', 'Nível profissão')
        stub.safe_text = lambda v, maximum=110: str(v or '')[:maximum]
        with patch.dict(sys.modules, {'core': stub}):
            rows = normalize_members(SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertNotIn('UID', rows[0])
        self.assertEqual(rows[0]['Profissão (código)'], 'Tipo 101')
        self.assertEqual(rows[1]['Nível profissão'], '55')


if __name__ == '__main__':
    unittest.main()

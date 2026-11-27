import threading
import unittest
from datetime import datetime, timedelta, timezone
from ds_cache import SharedSnapshotCache, CacheUnavailable, TTL, MAX_READS


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.monotonic = 0
        self.utc = datetime(2026,11,27,12,tzinfo=timezone.utc)
        self.cache = SharedSnapshotCache(lambda:self.monotonic,lambda:self.utc)
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return [{'match':{'starters':[]}}]

    def read(self, fetch=None):
        return self.cache.read(fetch or self.fetch,lambda exc:'DS-NETWORK')

    def advance(self, seconds=TTL):
        self.monotonic += seconds
        self.utc += timedelta(seconds=seconds)

    def test_cache_is_shared_and_immutable(self):
        rows = self.read()
        rows[0]['match']['starters'].append('mutation')
        for _ in range(100):
            self.assertEqual(self.read(),[{'match':{'starters':[]}}])
        self.assertEqual(self.calls,1)
        self.advance()
        self.read()
        self.assertEqual(self.calls,2)

    def test_concurrent_read(self):
        threads=[threading.Thread(target=self.read) for _ in range(30)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(self.calls,1)

    def test_failure_backoff(self):
        def fail():
            self.calls+=1
            raise OSError('private credentials')
        for _ in range(100):
            with self.assertRaisesRegex(CacheUnavailable,'DS-NETWORK'):self.read(fail)
        self.assertEqual(self.calls,1)
        self.advance()
        self.read()
        self.assertEqual(self.calls,2)

    def test_daily_cap_and_reset(self):
        for _ in range(MAX_READS):
            self.read();self.advance()
        self.read()
        self.assertEqual(self.calls,MAX_READS)
        self.assertEqual(self.cache.code,'DS-DAILY-LIMIT')
        self.utc=datetime(2026,11,28,0,tzinfo=timezone.utc)
        self.read()
        self.assertEqual(self.calls,MAX_READS+1)

    def test_cutoff_drops_stale(self):
        self.utc=datetime(2026,11,28,5,59,tzinfo=timezone.utc)
        self.read();self.advance(61)
        with self.assertRaises(CacheUnavailable):self.read(lambda:None)
        self.assertIsNone(self.cache.cached)

    def test_empty_snapshot_cached(self):
        self.read(lambda:[])
        self.assertEqual(self.read(),[])
        self.assertEqual(self.calls,0)

    def test_oversized_response_rejected(self):
        with self.assertRaisesRegex(CacheUnavailable,'DS-TOO-LARGE'):
            self.read(lambda:[{'match':{'x':'x'*140000}}])
        self.assertIsNone(self.cache.cached)

if __name__=='__main__':unittest.main()

"""Process-local shared read budget; no scheduled polling or database writes."""
import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone

TTL = 300
MAX_READS = 96
MAX_BYTES = 131072


class CacheUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def week_cutoff(now):
    now = now.astimezone(timezone.utc)
    saturday = (now - timedelta(days=(now.weekday()-5)%7)).replace(hour=6, minute=0, second=0, microsecond=0)
    return saturday if saturday <= now else saturday-timedelta(days=7)


class SharedSnapshotCache:
    def __init__(self, clock=time.monotonic, utc_now=None):
        self.clock = clock
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.day = None
        self.week = None
        self.attempts = 0
        self.until = 0
        self.cached = None
        self.status = 'empty'
        self.code = 'DS-UNKNOWN'

    def read(self, fetch, classify):
        with self.lock:
            now = self.utc_now().astimezone(timezone.utc)
            if self.day != now.date():
                self.day = now.date()
                self.attempts = 0
            week = week_cutoff(now)
            if self.week != week:
                self.week = week
                self.cached = None
                self.until = 0
            if self.clock() < self.until:
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise CacheUnavailable(self.code)
            if self.attempts >= MAX_READS:
                self.status = 'stale'
                self.code = 'DS-DAILY-LIMIT'
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise CacheUnavailable(self.code)
            self.attempts += 1
            try:
                rows = fetch()
                if not isinstance(rows, list) or len(rows)>8 or any(not isinstance(r,dict) or not isinstance(r.get('match'),dict) for r in rows):
                    raise CacheUnavailable('DS-CONFIG-OR-RESPONSE')
                if len(json.dumps(rows,ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
                    raise CacheUnavailable('DS-TOO-LARGE')
                # A slow request crossing the Saturday cutoff must not resurrect old data.
                if week_cutoff(self.utc_now()) != week:
                    self.week = None
                    self.cached = None
                    raise CacheUnavailable('DS-WEEK-CHANGED')
                self.cached = copy.deepcopy(rows)
                self.status = 'fresh'
                self.code = ''
                return copy.deepcopy(self.cached)
            except Exception as exc:
                self.status = 'stale'
                self.code = exc.code if isinstance(exc,CacheUnavailable) else classify(exc)
                if self.cached is not None:
                    return copy.deepcopy(self.cached)
                raise CacheUnavailable(self.code) from None
            finally:
                # Includes failures: repeated browser refreshes cannot create a retry storm.
                self.until = self.clock()+TTL

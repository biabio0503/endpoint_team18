"""Shared public catalog cache, independent of DB backend and student profiles.

One refresh per kind per process. Render workers each have their own bounded cache.
Failure backoff also prevents tab/focus/retry storms. No expired fallback records.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import os
from threading import Lock
import time

from providers.external.contestkorea import KINDS, collect_kind

CACHE_SECONDS = 1800
FAILURE_SECONDS = 120


class ActivityCatalog:
    def __init__(self, collect=collect_kind, clock=time.monotonic):
        self.collect, self.clock = collect, clock
        self.entries = {}
        self.locks = {kind: Lock() for kind in KINDS}

    def get_kind(self, kind, key):
        fingerprint = sha256(key.encode()).digest()
        with self.locks[kind]:
            cached = self.entries.get(kind)
            if cached and cached[0] == fingerprint and self.clock() < cached[1]:
                return cached[2], {**cached[3], 'cache_hit': True}
            result = self.collect(kind, key)
            metadata = {'kind': kind, 'status': result.status, 'error_code': result.error_code,
                        'fetched_at': datetime.now(timezone.utc).isoformat(), 'cache_hit': False,
                        'categories': result.categories, 'failed_categories': result.failed_categories,
                        'unverified_periods': result.unverified_periods,
                        'rejected_items': result.rejected_items, 'collected': len(result.items)}
            ttl = CACHE_SECONDS if result.status == 'success' else FAILURE_SECONDS
            self.entries[kind] = (fingerprint, self.clock() + ttl, result.items, metadata)
            return result.items, dict(metadata)

    def get(self):
        key = os.environ.get('CONTESTKOREA_API_KEY', '').strip()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda kind: self.get_kind(kind, key), KINDS))
        unique = {}
        for items, _ in results:
            for item in items:
                unique.setdefault(item['id'], item)
        return list(unique.values()), [meta for _, meta in results]


catalog = ActivityCatalog()

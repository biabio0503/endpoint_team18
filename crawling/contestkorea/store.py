"""Date history stores references, unchanged listing content is stored once."""
from hashlib import sha256
import json

from crawling.dacon.store import Store as DailyStore
from crawling.contestkorea.collector import compact_records


class Store(DailyStore):
    run_table = 'contestkorea_collection_runs'
    snapshot_table = 'contestkorea_daily_snapshots'
    item_table = 'contestkorea_daily_items'

    def __init__(self, connection, clock=None, lock_key=1800911):
        super().__init__(connection, clock, lock_key)

    def validate(self, records):
        return compact_records(records, self.clock())

    def publish(self, day, run_id, finished, records):
        from psycopg.types.json import Jsonb
        self.db.execute('''INSERT INTO contestkorea_daily_snapshots
            (collection_date, run_id, succeeded_at, collected_count) VALUES (%s,%s,%s,%s)
            ON CONFLICT (collection_date) DO UPDATE SET run_id=excluded.run_id,
            succeeded_at=excluded.succeeded_at, collected_count=excluded.collected_count''',
            (day, run_id, finished, len(records)))
        self.db.execute('DELETE FROM contestkorea_daily_items WHERE collection_date=%s', (day,))
        for item in records:
            digest = sha256(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).digest()
            self.db.execute('''INSERT INTO contestkorea_item_versions (content_hash,payload)
                VALUES (%s,%s) ON CONFLICT (content_hash) DO NOTHING''', (digest, Jsonb(item)))
            self.db.execute('''INSERT INTO contestkorea_daily_items (collection_date,original_id,content_hash)
                VALUES (%s,%s,%s)''', (day, item['id'], digest))
        # Same-day replacements can leave obsolete versions. Historical refs are
        # retained; only completely unreferenced content is reclaimed.
        self.db.execute('''DELETE FROM contestkorea_item_versions v WHERE NOT EXISTS
            (SELECT 1 FROM contestkorea_daily_items i WHERE i.content_hash=v.content_hash)''')

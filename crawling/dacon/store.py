"""One dedicated PostgreSQL session owns the lock from discovery to publication."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
LOCK_KEY = 1800910


class Store:
    # SQL identifiers are fixed by server-side subclasses, never request/CLI input.
    run_table = "dacon_collection_runs"
    snapshot_table = "dacon_daily_snapshots"
    item_table = "dacon_daily_items"

    def __init__(self, connection, clock=None, lock_key=LOCK_KEY):
        self.db = connection  # psycopg connection; autocommit, direct/session pooler
        self.clock = clock or (lambda: datetime.now(KST))
        self.lock_key = lock_key

    def _record(self, run_id, day, mode, status, started):
        self.db.execute(f'''INSERT INTO {self.run_table}
            (id, collection_date, mode, status, started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s)''',
            (run_id, day, mode, status, started, None if status == 'running' else self.clock()))
        return {'run_id': run_id, 'collection_date': str(day), 'mode': mode, 'status': status}

    def run(self, collect, mode='manual'):
        if mode not in ('scheduled', 'manual'):
            raise ValueError('invalid_mode')
        started = self.clock().astimezone(KST)
        day, run_id = started.date(), str(uuid4())
        acquired = self.db.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (self.lock_key,)).fetchone()['acquired']
        if not acquired:
            return self._record(run_id, day, mode, 'already_running', started)
        result = None
        try:
            # A crashed process loses its session lock. Only the next lock owner
            # may declare its unfinished attempt interrupted. No timeout steals a lock.
            self.db.execute(f"""UPDATE {self.run_table} SET status='failed',
                finished_at=%s, error_code='interrupted' WHERE status='running'""", (started,))
            if mode == 'scheduled' and self.db.execute(f"""SELECT 1 FROM {self.run_table}
                WHERE collection_date=%s AND mode='scheduled' AND status='success' LIMIT 1""", (day,)).fetchone():
                return self._record(run_id, day, mode, 'already_succeeded', started)
            result = self._record(run_id, day, mode, 'running', started)
            # Import validation here: the API never imports a crawler or Playwright.
            records = self.validate(collect())
            finished = self.clock().astimezone(KST)
            with self.db.transaction():
                self.publish(day, run_id, finished, records)
                self.db.execute(f"""UPDATE {self.run_table} SET status='success',
                    finished_at=%s, collected_count=%s WHERE id=%s""", (finished, len(records), run_id))
            return {**result, 'status': 'success', 'collected_count': len(records),
                    'succeeded_at': finished.isoformat()}
        except BaseException as error:
            if result:
                # Error bodies/DSNs are not persisted; the old snapshot is untouched.
                code = 'interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else type(error).__name__
                self.db.execute(f"""UPDATE {self.run_table} SET status='failed',
                    finished_at=%s, error_code=%s WHERE id=%s""", (self.clock(), code, run_id))
                if isinstance(error, Exception):
                    return {**result, 'status': 'failed', 'error_code': code, 'collected_count': None}
            raise
        finally:
            self.db.execute('SELECT pg_advisory_unlock(%s)', (self.lock_key,))

    def validate(self, records):
        from crawling.dacon.validation import validate_records
        return validate_records(records)

    def publish(self, day, run_id, finished, records):
        from psycopg.types.json import Jsonb
        self.db.execute(f'''INSERT INTO {self.snapshot_table}
            (collection_date, run_id, succeeded_at, collected_count) VALUES (%s,%s,%s,%s)
            ON CONFLICT (collection_date) DO UPDATE SET run_id=excluded.run_id,
            succeeded_at=excluded.succeeded_at, collected_count=excluded.collected_count''',
            (day, run_id, finished, len(records)))
        self.db.execute(f'DELETE FROM {self.item_table} WHERE collection_date=%s', (day,))
        with self.db.cursor() as cursor:
            cursor.executemany(f'''INSERT INTO {self.item_table}
                (collection_date, source, original_id, payload) VALUES (%s,%s,%s,%s)''',
                [(day, item['source'], item['original_id'], Jsonb(item)) for item in records])

    def status(self, day=None):
        where, args = ('WHERE collection_date=%s', (day,)) if day else ('', ())
        snapshot = self.db.execute(f'''SELECT * FROM {self.snapshot_table} {where}
            ORDER BY collection_date DESC LIMIT 1''', args).fetchone()
        runs = self.db.execute(f'''SELECT * FROM {self.run_table} {where}
            ORDER BY run_order DESC LIMIT 20''', args).fetchall()
        return {'snapshot': snapshot, 'recent_runs': runs}

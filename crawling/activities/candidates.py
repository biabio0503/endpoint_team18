"""Server-only current catalog. Daily discovery history is owned by source stores."""
from datetime import datetime, timedelta
from psycopg.types.json import Jsonb
from services.activity_eligibility import eligible_target, period_status


def identity(item):
    source = item.get('source', 'contestkorea')
    return source, item.get('original_id') or item['id'].removeprefix(source + ':')


def state(item, now):
    if item.get('application_cancelled'):
        return 'cancelled', None
    if item.get('application_closed') or item.get('status') in ('마감', '종료', '연습'):
        return 'closed', None
    if not eligible_target(item.get('target') or ''):
        return 'ineligible', None
    if item.get('source') in ('dacon', 'daker'):
        start, end = item.get('application_start_at'), item.get('application_end_at')
        if not start or not end or not item.get('application_evidence') or not item.get('eligibility_text'):
            return 'unknown', None
        deadline = datetime.fromisoformat(end)
        return ('expired' if now >= deadline else 'active'), deadline
    period = period_status(item.get('verified_period') or item.get('period') or '', now)
    deadline = datetime.fromisoformat(period['closes_at']) if period.get('closes_at') else None
    return {'closed': 'expired', 'open': 'active', 'upcoming': 'active'}.get(period['status'], 'unknown'), deadline


class Candidates:
    def __init__(self, db, sources, now):
        self.db, self.sources, self.now = db, list(sources), now

    def classify_history(self):
        # Backfilled historical content is classified once, without any HTTP.
        for row in self.db.execute("SELECT * FROM activity_candidates WHERE source=ANY(%s) AND state='pending' AND last_success_at IS NOT NULL", (self.sources,)).fetchall():
            item = {**row['payload'], 'source': row['source']}
            status, deadline = state(item, self.now)
            self.db.execute('UPDATE activity_candidates SET state=%s, deadline_at=%s WHERE source=%s AND original_id=%s',
                            (status, deadline, row['source'], row['original_id']))
        self.db.execute("""UPDATE activity_candidates SET state='expired' WHERE source=ANY(%s)
            AND state='active' AND deadline_at <= %s""", (self.sources, self.now))

    def due(self, observed):
        self.classify_history()
        rows = self.db.execute("""SELECT * FROM activity_candidates WHERE source=ANY(%s) AND (
            (last_success_at IS NULL AND next_check_at <= %s) OR (state='active'
            AND (deadline_at IS NULL OR deadline_at > %s)
            AND (missing_since IS NULL OR next_check_at <= %s))) ORDER BY next_check_at,source,original_id""",
            (self.sources, self.now, self.now, self.now)).fetchall()
        return [{**row['payload'], 'source': row['source'], 'original_id': row['original_id']}
                for row in rows if (row['source'], row['original_id']) not in observed]

    def mark_missing(self, observed):
        for row in self.db.execute("SELECT source,original_id FROM activity_candidates WHERE source=ANY(%s) AND state='active' AND missing_since IS NULL", (self.sources,)).fetchall():
            if (row['source'], row['original_id']) not in observed:
                self.db.execute('UPDATE activity_candidates SET missing_since=%s WHERE source=%s AND original_id=%s',
                                (self.now, row['source'], row['original_id']))

    def apply(self, item, *, seen):
        source, original_id = identity(item)
        if item.get('detail_reused'):
            if seen:
                self.db.execute('UPDATE activity_candidates SET last_seen_at=%s, missing_since=NULL WHERE source=%s AND original_id=%s',
                                (self.now, source, original_id))
            return
        error = item.get('verification_error') or ('parse_error' if item.get('period_source') == 'unverified' else None)
        if error:
            # Preserve payload, deadline and last_success_at on temporary errors.
            self.db.execute('''INSERT INTO activity_candidates
                (source,original_id,payload,state,first_seen_at,last_seen_at,last_checked_at,
                 last_success_at,next_check_at,check_status,missing_since)
                VALUES (%s,%s,%s,'pending',%s,%s,%s,NULL,%s,%s,%s)
                ON CONFLICT (source,original_id) DO UPDATE SET
                last_checked_at=excluded.last_checked_at,check_status=excluded.check_status,
                next_check_at=excluded.next_check_at,
                last_seen_at=CASE WHEN %s THEN excluded.last_seen_at ELSE activity_candidates.last_seen_at END,
                missing_since=CASE WHEN %s THEN NULL ELSE activity_candidates.missing_since END''',
                (source, original_id, Jsonb(item), self.now, self.now, self.now,
                 self.now + timedelta(hours=1), error, None if seen else self.now, seen, seen))
            return
        status, deadline = state(item, self.now)
        self.db.execute('''INSERT INTO activity_candidates
            (source,original_id,payload,state,deadline_at,first_seen_at,last_seen_at,last_checked_at,last_success_at,
             next_check_at,check_status,missing_since)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'success',%s)
            ON CONFLICT (source,original_id) DO UPDATE SET payload=excluded.payload,state=excluded.state,
            deadline_at=excluded.deadline_at,last_checked_at=excluded.last_checked_at,
            last_success_at=excluded.last_success_at,next_check_at=excluded.next_check_at,check_status='success',
            last_seen_at=CASE WHEN %s THEN excluded.last_seen_at ELSE activity_candidates.last_seen_at END,
            missing_since=CASE WHEN %s THEN NULL ELSE activity_candidates.missing_since END''',
            (source, original_id, Jsonb(item), status, deadline, self.now, self.now, self.now, self.now,
             self.now + timedelta(hours=20), None if seen else self.now, seen, seen))

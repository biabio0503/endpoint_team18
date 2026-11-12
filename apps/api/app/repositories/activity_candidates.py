"""Read only current candidates. No provider/crawler import or external fallback."""
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo


def read(db, source):
    # Identifiers are an internal allowlist. Values remain query parameters.
    prefix, sources = ('contestkorea', ('contestkorea',)) if source == 'contestkorea' else ('dacon', ('dacon', 'daker'))
    rows = db.execute(f"""SELECT c.* FROM activity_candidates c
        WHERE c.source IN ({','.join('?' for _ in sources)}) AND c.state IN ('active','pending')
        ORDER BY c.source,c.original_id""", sources).fetchall()
    latest = db.execute(f'''SELECT status,finished_at,metrics FROM {prefix}_collection_runs
        WHERE status IN ('success','partial','failed') ORDER BY run_order DESC LIMIT 1''').fetchone()
    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        if row['deadline_at'] and row['deadline_at'] < now:
            continue
        payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
        items.append({**payload, 'source': row['source'], 'original_id': row['original_id'],
                      'last_seen_at': row['last_seen_at'].isoformat(),
                      'last_checked_at': row['last_checked_at'].isoformat() if row['last_checked_at'] else None,
                      'last_success_at': row['last_success_at'].isoformat(), 'check_status': row['check_status'],
                      'missing_from_latest_list': row['missing_since'] is not None,
                      'stale': row['check_status'] not in ('success',) or now - row['last_success_at'] > timedelta(hours=26),
                      'collection_date': row['last_seen_at'].astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()})
    failed = latest and latest['status'] in ('failed', 'partial')
    metadata = {'source': source, 'kind': 'competition', 'status': ('partial' if items else 'error') if failed else 'success' if latest or rows else 'error',
                'error_code': 'last_collection_failed' if latest and latest['status'] == 'failed' else
                              'collection_incomplete' if failed else None if latest or rows else 'no_successful_collection',
                'collected': len(items), 'fetched_at': max((i['last_success_at'] for i in items), default=None),
                'stale_candidates': sum(i['stale'] for i in items),
                'metrics': latest['metrics'] if latest else {}, 'cache_hit': False}
    return items, metadata

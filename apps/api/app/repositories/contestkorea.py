"""DB only; student requests never contact Contest Korea."""
import json
import logging

logger = logging.getLogger(__name__)


def load_catalog(db):
    metadata = {'source': 'contestkorea', 'kind': 'competition', 'status': 'error',
                'error_code': 'no_successful_collection', 'collected': 0, 'fetched_at': None, 'cache_hit': False}
    if getattr(db, 'backend', None) != 'postgres':
        return [], {**metadata, 'error_code': 'not_configured'}
    try:
        rows = db.execute('''SELECT s.collection_date, s.succeeded_at, s.collected_count, v.payload,
                (SELECT status FROM contestkorea_collection_runs
                 WHERE status IN ('running','success','failed') ORDER BY run_order DESC LIMIT 1) AS latest_status
            FROM (SELECT * FROM contestkorea_daily_snapshots ORDER BY collection_date DESC LIMIT 1) s
            LEFT JOIN contestkorea_daily_items i ON i.collection_date=s.collection_date
            LEFT JOIN contestkorea_item_versions v ON v.content_hash=i.content_hash
            ORDER BY i.original_id''').fetchall()
        if not rows:
            return [], metadata
        snapshot, items = rows[0], []
        for row in rows:
            if not row['payload']:
                continue
            payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            items.append({'category': '', 'host': '', **payload, 'source': 'contestkorea',
                          'source_label': '콘테스트코리아', 'collection_date': str(snapshot['collection_date'])})
        failed = snapshot['latest_status'] == 'failed'
        return items, {**metadata, 'status': 'partial' if failed else 'success',
                       'error_code': 'last_collection_failed' if failed else None,
                       'collected': snapshot['collected_count'],
                       'fetched_at': snapshot['succeeded_at'].isoformat(),
                       'collection_date': str(snapshot['collection_date'])}
    except Exception:
        logger.warning('Contest Korea snapshot unavailable')
        return [], {**metadata, 'error_code': 'snapshot_unavailable'}

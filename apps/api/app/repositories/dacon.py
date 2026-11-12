"""Read-only adapter. No crawler/Playwright dependency or network fallback."""
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


def load_catalog(db):
    metadata = {'source': 'dacon_daker', 'kind': 'competition', 'status': 'error',
                'error_code': 'no_successful_collection', 'collected': 0, 'fetched_at': None,
                'cache_hit': False}
    if getattr(db, 'backend', None) != 'postgres':
        return [], {**metadata, 'error_code': 'not_configured'}
    try:
        # A single statement snapshot also preserves successful empty collections.
        rows = db.execute('''SELECT s.collection_date, s.succeeded_at, s.collected_count, i.payload,
                (SELECT status FROM dacon_collection_runs
                 WHERE status IN ('running','success','failed') ORDER BY run_order DESC LIMIT 1) AS latest_status
            FROM (SELECT * FROM dacon_daily_snapshots ORDER BY collection_date DESC LIMIT 1) s
            LEFT JOIN dacon_daily_items i ON i.collection_date=s.collection_date
            ORDER BY i.source, i.original_id''').fetchall()
        if not rows:
            return [], metadata
        snapshot = rows[0]
        items = []
        for row in rows:
            payload = row['payload']
            if not payload:
                continue
            if isinstance(payload, str):
                payload = json.loads(payload)
            start, end = payload.get('application_start_at'), payload.get('application_end_at')
            if (payload.get('status') not in ('진행중', '모집중') or payload.get('application_closed') or not start or not end
                    or not payload.get('application_evidence') or not payload.get('eligibility_text')):
                continue
            # Convert explicit registration timestamps for the shared matcher.
            a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if a.tzinfo is None or b.tzinfo is None:
                continue
            source = payload['source']
            items.append({'id': payload['id'], 'original_id': payload['original_id'],
                          'source': source, 'source_label': '데이커' if source == 'daker' else '데이콘',
                          'kind': 'competition', 'title': payload['title'], 'url': payload['url'],
                          'host': payload.get('host'), 'category': payload.get('category') or '',
                          'description_text': (payload.get('description') or payload.get('overview') or '')[:2000],
                          'target': payload.get('target') or '', 'eligibility_text': payload['eligibility_text'],
                          'period': payload['application_period'], 'period_source': 'original_page',
                          'application_start_at': start, 'application_end_at': end,
                          'collection_date': str(snapshot['collection_date'])})
        failed = snapshot['latest_status'] == 'failed'
        return items, {**metadata, 'status': 'partial' if failed else 'success',
                       'error_code': 'last_collection_failed' if failed else None,
                       'collected': snapshot['collected_count'], 'verified_candidates': len(items),
                       'fetched_at': snapshot['succeeded_at'].isoformat(),
                       'collection_date': str(snapshot['collection_date'])}
    except Exception:
        logger.warning('Dacon snapshot unavailable')
        return [], {**metadata, 'error_code': 'snapshot_unavailable'}

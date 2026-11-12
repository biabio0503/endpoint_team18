"""Read-only adapter. No crawler/Playwright dependency or network fallback."""
from datetime import datetime
import logging
from repositories.activity_candidates import read

logger = logging.getLogger(__name__)


def load_catalog(db):
    metadata = {'source': 'dacon_daker', 'kind': 'competition', 'status': 'error',
                'collected': 0, 'fetched_at': None, 'cache_hit': False}
    if getattr(db, 'backend', None) != 'postgres':
        return [], {**metadata, 'error_code': 'not_configured'}
    try:
        rows, meta = read(db, 'dacon_daker')
        items = []
        for payload in rows:
            start, end = payload.get('application_start_at'), payload.get('application_end_at')
            if (payload.get('application_closed') or payload.get('application_cancelled') or not start or not end
                    or not payload.get('application_evidence') or not payload.get('eligibility_text')
                    or payload.get('status') in ('종료', '마감', '연습')):
                continue
            a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if a.tzinfo is None or b.tzinfo is None:
                continue
            source = payload['source']
            items.append({**payload, 'source_label': '데이커' if source == 'daker' else '데이콘',
                          'kind': 'competition', 'category': payload.get('category') or '',
                          'description_text': (payload.get('description') or payload.get('overview') or '')[:2000],
                          'target': payload.get('target') or '', 'period': payload['application_period'],
                          'period_source': 'original_page'})
        return items, {**meta, 'verified_candidates': len(items)}
    except Exception:
        logger.warning('Dacon candidates unavailable')
        return [], {**metadata, 'error_code': 'snapshot_unavailable'}

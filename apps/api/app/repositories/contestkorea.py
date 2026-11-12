"""DB only; student requests never contact Contest Korea."""
import logging
from repositories.activity_candidates import read

logger = logging.getLogger(__name__)


def load_catalog(db, *, include_event_context=False):
    metadata = {'source': 'contestkorea', 'kind': 'competition', 'status': 'error',
                'collected': 0, 'fetched_at': None, 'cache_hit': False}
    if getattr(db, 'backend', None) != 'postgres':
        return [], {**metadata, 'error_code': 'not_configured'}
    try:
        rows, meta = read(db, 'contestkorea', include_event_context=include_event_context)
        return [{'category': '', 'host': '', **item, 'source_label': '콘테스트코리아'} for item in rows], meta
    except Exception:
        logger.warning('Contest Korea candidates unavailable')
        return [], {**metadata, 'error_code': 'snapshot_unavailable'}

"""Collect both public kinds, storing only open/upcoming undergraduate listings."""
from datetime import datetime
import os
import sys

from providers.external.contestkorea import KINDS, collect_kind, original_url
from services.activity_eligibility import KST, eligible_target, period_status, contestkorea_in_scope
import re
from crawling.activities.batch import Batch


def collect(*, known=None):
    now = datetime.now(KST)
    key = os.environ.get('CONTESTKOREA_API_KEY', '').strip()
    items, metrics, statuses = {}, {}, []
    detail_cache = {}
    for kind in KINDS:
        result = collect_kind(kind, key, eligible_only=True, now=now, detail_cache=detail_cache, known_details=known)
        statuses.append(result.status)
        for field in ('categories', 'failed_categories', 'rejected_items', 'fetched_items', 'eligible_items',
                      'unknown_periods', 'parse_failures', 'network_failures', 'limited_categories', 'reused_details',
                      'skipped_closed', 'detail_requests'):
            metrics[field] = metrics.get(field, 0) + getattr(result, field)
        metrics.setdefault('missing_categories', {})[kind] = list(result.missing_categories)
        for item in result.observations or result.items:
            items.setdefault(item['id'], item)
        print(f'[contestkorea] {kind}: {result.status}, fetched={result.fetched_items}, '
              f'skipped_closed={result.skipped_closed}, detail_requests={result.detail_requests}, '
              f'eligible={result.eligible_items}, missing_categories={list(result.missing_categories)}, unknown={result.unknown_periods}, '
              f'parse_failures={result.parse_failures}, network_failures={result.network_failures}',
              file=sys.stderr, flush=True)
    status = 'error' if all(s == 'error' for s in statuses) else 'partial' if any(s != 'success' for s in statuses) else 'success'
    return Batch(list(items.values()), status, metrics)


def compact_records(records, now):
    """Fail on malformed records; deliberately omit closed/unverified/ineligible ones."""
    if not isinstance(records, list):
        raise ValueError('invalid_collection')
    unique = {}
    for record in records:
        if (not isinstance(record, dict) or record.get('source') != 'contestkorea'
                or not isinstance(record.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', record['id'])
                or record.get('kind') not in KINDS
                or any(not isinstance(record.get(field), str) for field in ('title', 'category', 'host', 'target', 'period', 'url'))
                or not record['title'].strip()):
            raise ValueError('invalid_record')
        original_url(record['url'])
        if (not contestkorea_in_scope(record) or record.get('verification_error') or record.get('period_source') in ('unknown', 'unverified')
                or record.get('application_closed') or record.get('application_cancelled')
                or not eligible_target(record['target']) or
                period_status(record.get('verified_period') or record['period'], now)['status'] not in ('open', 'upcoming')):
            continue
        # No raw API responses, HTML, posters, binaries, or repeated derived fields.
        fields = ('id', 'kind', 'title', 'category', 'host', 'target', 'period', 'url', 'verified_period', 'official_application_url')
        item = {key: record[key] for key in fields if record.get(key)}
        if item['id'] in unique and unique[item['id']] != item:
            raise ValueError('conflicting_duplicate')
        unique[item['id']] = item
    return list(unique.values())

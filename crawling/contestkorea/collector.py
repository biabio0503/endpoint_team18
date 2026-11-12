"""Collect both public kinds, storing only open/upcoming undergraduate listings."""
from datetime import datetime
import os
import sys

from providers.external.contestkorea import KINDS, collect_kind, original_url
from services.activity_eligibility import KST, eligible_target, period_status
import re


class CollectionIncomplete(Exception):
    pass


def collect():
    now = datetime.now(KST)
    key = os.environ.get('CONTESTKOREA_API_KEY', '').strip()
    items = []
    for kind in KINDS:
        result = collect_kind(kind, key, eligible_only=True, now=now)
        print(f'[contestkorea] {kind}: {result.status}, kept={len(result.items)}, '
              f'categories={result.categories}, failed_categories={result.failed_categories}, '
              f'unverified_periods={result.unverified_periods}, failed_details={result.failed_details}',
              file=sys.stderr, flush=True)
        if result.status != 'success':
            # Never publish a partial category/kind snapshot as a complete day.
            raise CollectionIncomplete(result.error_code or 'collection_incomplete')
        items.extend(result.items)
    return items


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
        if (not eligible_target(record['target']) or
                period_status(record.get('verified_period') or record['period'], now)['status'] not in ('open', 'upcoming')):
            continue
        # No raw API responses, HTML, posters, binaries, or repeated derived fields.
        fields = ('id', 'kind', 'title', 'category', 'host', 'target', 'period', 'url', 'verified_period')
        item = {key: record[key] for key in fields if record.get(key)}
        if item['id'] in unique and unique[item['id']] != item:
            raise ValueError('conflicting_duplicate')
        unique[item['id']] = item
    return list(unique.values())

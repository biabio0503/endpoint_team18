"""Conservative identity: an explicit application link, never a publisher permalink."""
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def official_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return None
        # Publisher detail links are provenance, not evidence of an application.
        if p.hostname.lower().removeprefix('www.') == 'contestkorea.com':
            return None
        if any(k.lower() in ('apikey', 'api_key', 'token') for k, _ in parse_qsl(p.query)):
            return None
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(sorted(query)), p.fragment))
    except ValueError:
        return None


def normalized_text(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def same_event(a, b):
    if a.get('source') == b.get('source'):
        return False
    # A recurring application URL must not collapse different editions/periods.
    dates_a, dates_b = (a.get('opens_at'), a.get('closes_at')), (b.get('opens_at'), b.get('closes_at'))
    for pattern in (r'20\d{2}', r'\d+\s*회', r'\d+\s*기', r'season\s*\d+'):
        editions = [{re.sub(r'\s+', '', token) for token in re.findall(pattern, normalized_text(x.get('title')))} for x in (a,b)]
        if editions[0] and editions[1] and editions[0] != editions[1]:
            return False
    if not any(dates_a) and normalized_text(a.get('title')) != normalized_text(b.get('title')):
        return False
    ua, ub = official_url(a.get('official_application_url')), official_url(b.get('official_application_url'))
    if ua and ub:
        # A publisher may omit the official closing hour. Registration days and
        # explicit editions still prevent merging a reused URL across rounds.
        return ua == ub and registration_days(dates_a) == registration_days(dates_b)
    return (all(a.get(k) and b.get(k) and normalized_text(a[k]) == normalized_text(b[k])
                for k in ('host', 'title')) and all(dates_a) and dates_a == dates_b)


def registration_days(dates):
    return tuple(value.split('T')[0] if value else None for value in dates)


def candidate_keys(item):
    dates = item.get('opens_at'), item.get('closes_at')
    url = official_url(item.get('official_application_url'))
    keys = [('url', url, registration_days(dates))] if url else []
    if item.get('host') and item.get('title') and all(dates):
        keys.append(('fallback', normalized_text(item['host']), normalized_text(item['title']), dates))
    return keys


def merge_events(ranked):
    groups, index = [], {}
    for item in ranked:
        # Require agreement with every member: missing URLs must not bridge two
        # contradictory official URLs or different editions transitively.
        keys = candidate_keys(item)
        possible = sorted({i for key in keys for i in index.get(key, [])})
        number = next((i for i in possible if all(same_event(item, member) for member in groups[i])), None)
        if number is None:
            number = len(groups)
            groups.append([item])
        else:
            groups[number].append(item)
        for key in keys:
            index.setdefault(key, set()).add(number)
    result = []
    for group in groups:
        links = [{'source': x.get('source', 'contestkorea'), 'source_label': x.get('source_label', '콘테스트코리아'),
                  'original_id': x.get('original_id', x['id']), 'url': x.get('url'),
                  'last_success_at': x.get('last_success_at'), 'check_status': x.get('check_status'),
                  'stale': x.get('stale', False)} for x in group]
        result.append({**group[0], 'source_links': links,
                       'source_label': ' · '.join(x['source_label'] for x in links)})
    return result

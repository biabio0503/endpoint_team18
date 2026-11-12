"""Contest Korea Basic DEMO v1.1. Public records only; never log transport errors.

urllib is intentional: HTTP client INFO logs must not emit apikey query strings.
The legacy fixture adapters are never a fallback for this provider.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit, parse_qsl
from urllib.request import Request, build_opener, HTTPRedirectHandler
from lxml import html

BASE = 'https://www.contestkorea.com'
KINDS = {'competition': '1', 'extracurricular': '2'}
FIELDS = ('STR_MEETCODE', 'STR_MEETING', 'STR_MENU', 'STR_HOST', 'STR_TARGET', 'STR_DATE1', 'STR_URL')
MAX_BYTES = 2 * 1024 * 1024


class ProviderError(Exception):
    """Only fixed internal codes, never a URL, response body or original exception."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(endpoint, params, key):
    if not key:
        raise ProviderError('not_configured')
    try:
        request = Request(BASE + '/api/' + endpoint + '?' + urlencode({**params, 'apikey': key}),
                          headers={'Accept': 'application/json', 'User-Agent': 'Team18-Activity/1.0'})
        with build_opener(NoRedirect).open(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        # Reject accidental credential echo before any field can enter the cache.
        text = raw.decode('utf-8-sig')
        payload = json.loads(text)
        if key in json.dumps(payload, ensure_ascii=False):
            raise ValueError
        return payload
    except Exception:
        raise ProviderError('provider_unavailable') from None


def rows(payload):
    # Verified live v1.1 envelope: [{resultcode: '1', resultmsg: '성공', Data: [...]}].
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict) and 'resultcode' in payload[0]:
        if str(payload[0]['resultcode']) != '1' or not isinstance(payload[0].get('Data'), list):
            raise ProviderError('invalid_response')
        payload = payload[0]['Data']
    if not isinstance(payload, list) or len(payload) > 2000:
        raise ProviderError('invalid_response')
    for item in payload:
        if not isinstance(item, dict) or 'resultcode' in {k.lower() for k in item}:
            raise ProviderError('invalid_response')
    return payload


def clean(value):
    if not isinstance(value, (str, int)):
        return ''
    # Titles can contain literal <AI 챌린지> or <발효>; strip only known HTML tags.
    return ' '.join(re.sub(r'</?(?:br|p|span|b|strong|em|i|div)(?:\s+[^>]*)?\s*/?>', ' ', unescape(str(value)), flags=re.I).split())[:2000]


def original_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError
    value = urljoin(BASE, unescape(value.strip()))
    parsed = urlsplit(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
            or any(ord(c) < 33 for c in value) or parsed.path.startswith('/api/')
            or any(k.lower() in ('apikey', 'api_key') for k, _ in parse_qsl(parsed.query))):
        raise ValueError
    return value


def normalize(item, kind):
    if not all(field in item for field in FIELDS):
        raise ValueError
    record = dict(zip(('id', 'title', 'category', 'host', 'target', 'period', 'url'),
                      (clean(item[field]) for field in FIELDS)))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', record['id']) or not record['title']:
        raise ValueError
    record['url'] = original_url(item['STR_URL'])
    query = dict(parse_qsl(urlsplit(record['url']).query))
    # The live category response can also contain promoted posts of the other kind.
    if query.get('Txt_gbn') in ('1', '2'):
        kind = next(k for k, v in KINDS.items() if v == query['Txt_gbn'])
    return {**record, 'kind': kind, 'source': 'contestkorea', 'source_label': '콘테스트코리아'}


def verify_period(record):
    """DEMO omits years. Verify the same public detail page; never guess from an ID.

    Preserve STR_DATE1 verbatim. Only trust a unique, explicit date range whose
    month/day endpoints agree with the API. Failure leaves it ineligible.
    """
    short = re.fullmatch(r'(\d{1,2})\.(\d{1,2})\s*~\s*(\d{1,2})\.(\d{1,2})', record['period'])
    if not short:
        return record
    try:
        url = urlsplit(record['url'])
        if (url.hostname not in ('www.contestkorea.com', 'contestkorea.com') or url.path != '/sub/view.php'
                or dict(parse_qsl(url.query)).get('str_no') != record['id']):
            raise ValueError
        request = Request(record['url'], headers={'User-Agent': 'Team18-Activity/1.0'})
        with build_opener(NoRedirect).open(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        page = html.fromstring(raw.decode('utf-8'))
        cells = page.xpath('//tr[th[normalize-space(.)="접수기간"]]/td')
        if len(cells) != 1:
            raise ValueError
        period = ' '.join(cells[0].text_content().split())
        full = re.fullmatch(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})\s*~\s*(20\d{2})\.(\d{1,2})\.(\d{1,2})', period)
        if not full or tuple(map(int, short.groups())) != tuple(int(full[i]) for i in (2, 3, 5, 6)):
            raise ValueError
        return {**record, 'verified_period': period, 'period_source': 'original_page'}
    except Exception:
        return {**record, 'period_source': 'unverified'}


@dataclass(frozen=True)
class Collection:
    items: tuple
    status: str
    categories: int = 0
    failed_categories: int = 0
    rejected_items: int = 0
    error_code: str | None = None
    unverified_periods: int = 0


def collect_kind(kind, key):
    if not key:
        return Collection((), 'error', error_code='not_configured')
    try:
        menu = rows(request_json('menu_info_api.php', {'int_gbn': KINDS[kind]}, key))
        codes = []
        for item in menu:
            fields = {k.upper(): v for k, v in item.items()}
            # Explicit code-field aliases; never infer codes from names or URLs.
            code = str(fields.get('STR_BCODE', '')).strip()
            if not re.fullmatch(r'\d{1,20}', code):
                raise ProviderError('invalid_menu')
            if code not in codes:
                codes.append(code)
        if not codes or len(codes) > 64:
            raise ProviderError('invalid_menu')
    except ProviderError as error:
        return Collection((), 'error', error_code=str(error))

    def category(code):
        try:
            return rows(request_json('meeting_info_api.php', {'Txt_bcode': code}, key))
        except ProviderError:
            return None

    unique, failed, rejected = {}, 0, 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for records in pool.map(category, codes):
            if records is None:
                failed += 1
                continue
            for item in records:
                try:
                    record = normalize(item, kind)
                    unique.setdefault(record['id'], record)
                except (ValueError, TypeError):
                    rejected += 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = tuple(pool.map(verify_period, unique.values()))
    unverified = sum(item.get('period_source') == 'unverified' for item in items)
    incomplete = failed or rejected or unverified
    status = 'error' if failed == len(codes) or (rejected and not unique) else 'partial' if incomplete else 'success'
    return Collection(items, status, len(codes), failed, rejected,
                      'collection_incomplete' if incomplete else None, unverified)

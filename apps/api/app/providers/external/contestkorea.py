"""Contest Korea Basic DEMO v1.1. Public records only; never log transport errors.

urllib is intentional: HTTP client INFO logs must not emit apikey query strings.
The legacy fixture adapters are never a fallback for this provider.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from hashlib import sha256
import json
import re
import sys
from urllib.parse import urlencode, urljoin, urlsplit, parse_qsl
from urllib.request import Request, build_opener, HTTPRedirectHandler
from lxml import html
from datetime import datetime
from services.activity_eligibility import KST, eligible_target, period_status
from services.activity_identity import official_url

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
    except OSError:
        raise ProviderError('provider_unavailable') from None
    except Exception:
        raise ProviderError('invalid_response') from None


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


def listing_signature(record):
    fields = ('id', 'title', 'category', 'host', 'target', 'period', 'url')
    return sha256(json.dumps({k: record.get(k, '') for k in fields}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


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
    signature = listing_signature(record)
    return {**record, 'kind': kind, 'source': 'contestkorea', 'source_label': '콘테스트코리아',
            'listing_signature': signature}


REGISTRATION_LABELS = {'접수기간', '신청기간', '모집기간', '참가신청기간', '참가접수기간'}
UNKNOWN_PERIODS = {'미정', '추후공지', '추후안내', '일정미정', '기간미정', '별도공지'}
CATEGORY_LIMIT = 1000  # Documented limitsu; no invented pagination parameters.


def label_text(value):
    return re.sub(r'[\s:：·ㆍ.]+', '', value)


def confirmed_state(value):
    """Read assertions, not future/conditional notices about closing.

    Strip each qualified closure separately, so a notice cannot hide a later
    explicit current state in the same cell.
    """
    closure = r'(?:조기\s*)?(?:(?:참가\s*)?(?:접수|신청|모집|대회|행사)(?:이|가)?\s*)?(?:마감|종료|취소)'
    value = re.sub(closure + r'\s*(?:될\s*수\s*있(?:습니다|어요|음|으며)?|가능(?:합니다|하지만|하며|함)?|예정(?:입니다|임)?|되지\s*않았[가-힣]*|시(?=\s|[,.)]|$)|일|까지)', '', value)
    cancelled = bool(re.search(r'(?:접수|모집|대회|행사)(?:이|가)?\s*취소|^취소[.!]?$', value.strip()))
    closed = bool(re.search(r'조기\s*마감|(?:접수|신청|모집)(?:이|가)?\s*(?:마감|종료)|^(?:마감|종료)[.!]?$', value.strip()))
    return cancelled, closed


def parse_detail(record, raw):
    page = html.fromstring(raw.decode('utf-8-sig'))
    cells = [tr.xpath('./td')[0] for tr in page.xpath('//tr[th]')
             if tr.xpath('./td') and label_text(tr.xpath('./th')[0].text_content()) in REGISTRATION_LABELS]
    period = clean(cells[0].text_content()) if len(cells) == 1 else ''
    # Only explicit registration/status cells may declare early closure. A global
    # navigation link or a submission/results date must never close a listing.
    state_cells = [tr.xpath('./td')[0] for tr in page.xpath('//tr[th]') if tr.xpath('./td')
                   and label_text(tr.xpath('./th')[0].text_content()) in {'접수상태', '모집상태', '진행상태'}]
    states = [period, *(clean(c.text_content()) for c in state_cells)]
    result = {k: v for k, v in record.items() if k not in
              ('verified_period', 'verification_error', 'application_closed', 'application_cancelled', 'official_application_url')}
    links = [official_url(urljoin(record['url'], a.get('href', ''))) for tr in page.xpath('//tr[th]')
             if label_text(tr.xpath('./th')[0].text_content()) in {'접수하기', '신청하기', '참가신청', '온라인접수'}
             for a in tr.xpath('./td//a[@href]')]
    links = set(filter(None, links))
    if len(links) == 1:
        result['official_application_url'] = links.pop()
    assertions = [confirmed_state(value) for value in states]
    if any(cancelled for cancelled, _ in assertions):
        return {**result, 'application_cancelled': True, 'period_source': 'original_page'}
    if any(closed for _, closed in assertions):
        return {**result, 'application_closed': True, 'period_source': 'original_page'}
    if len(cells) != 1:
        raise ValueError('registration_structure_changed')
    for tr in page.xpath('//tr[th][td]'):
        label = label_text(tr.xpath('./th')[0].text_content())
        if label in ('주최주관', '주최', '참가대상'):
            result['target' if label == '참가대상' else 'host'] = clean(tr.xpath('./td')[0].text_content())
    if label_text(period) in UNKNOWN_PERIODS:
        return {**result, 'period_source': 'unknown', 'period': period}
    if period_status(period, datetime.now(KST))['status'] == 'unknown':
        raise ValueError('registration_parse_failed')
    # The detail is authoritative, including extensions. Do not compare against
    # an old API month/day range when rechecking a previously discovered listing.
    return {**result, 'verified_period': period, 'period_source': 'original_page'}


def verify_period(record):
    """Read registration evidence on every detail check, including cancellation."""
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
        return parse_detail(record, raw)
    except OSError:
        return {**record, 'period_source': 'unverified', 'verification_error': 'network_error'}
    except Exception:
        return {**record, 'period_source': 'unverified', 'verification_error': 'parse_error'}


@dataclass(frozen=True)
class Collection:
    items: tuple
    status: str
    categories: int = 0
    failed_categories: int = 0
    rejected_items: int = 0
    error_code: str | None = None
    unverified_periods: int = 0
    failed_details: int = 0
    fetched_items: int = 0
    eligible_items: int = 0
    unknown_periods: int = 0
    parse_failures: int = 0
    network_failures: int = 0
    observations: tuple = ()
    limited_categories: int = 0
    reused_details: int = 0


def collect_kind(kind, key, *, eligible_only=False, now=None, detail_cache=None, known_details=None):
    now = (now or datetime.now(KST)).astimezone(KST)
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
        return Collection((), 'error', error_code=str(error),
                          network_failures=int(str(error) == 'provider_unavailable'),
                          parse_failures=int(str(error) != 'provider_unavailable'))

    def category(code):
        found, previous, requested = {}, set(), min(100, CATEGORY_LIMIT)
        try:
            while True:
                batch = rows(request_json('meeting_info_api.php', {'Txt_bcode': code, 'limitsu': requested}, key))
                ids = {str(item.get('STR_MEETCODE', '')) for item in batch}
                for item in batch:
                    found.setdefault(str(item.get('STR_MEETCODE', '')), item)
                if len(batch) < requested:
                    return list(found.values()), False, None
                if ids == previous or requested >= CATEGORY_LIMIT:
                    return list(found.values()), True, None
                previous, requested = ids, min(requested * 2, CATEGORY_LIMIT)
        except ProviderError as error:
            return list(found.values()), True, str(error)

    unique, failed, rejected, fetched, limited = {}, 0, 0, 0, 0
    skipped = {}
    category_network, category_parse = 0, 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for records in pool.map(category, codes):
            records, capped, error = records
            if error:
                failed += 1
                category_network += int(error == 'provider_unavailable')
                category_parse += int(error != 'provider_unavailable')
            limited += int(capped)
            fetched += len(records)
            for item in records:
                try:
                    record = normalize(item, kind)
                    old = (known_details or {}).get(record['id'])
                    unverified = old and old.get('_needs_verification')
                    # An authoritative unexpired detail must be checked even if
                    # the API listing still advertises its pre-extension date.
                    detail_active = old and not (old.get('application_closed') or old.get('application_cancelled')) and period_status(
                        old.get('verified_period') or old.get('period') or '', now)['status'] in ('open', 'upcoming')
                    if eligible_only and not detail_active and not unverified and (not eligible_target(record['target'])
                            or (period_status(record['period'], now)['status'] == 'closed' and not old)):
                        skipped.setdefault(record['id'], record)
                        continue
                    unique.setdefault(record['id'], record)
                except (ValueError, TypeError):
                    rejected += 1
    cache = detail_cache if detail_cache is not None else {}
    def verify(record):
        if record['id'] not in cache:
            old = (known_details or {}).get(record['id'])
            terminal = old and not old.get('_needs_verification') and (old.get('application_closed') or old.get('application_cancelled') or
                               period_status(old.get('verified_period') or old.get('period') or '', now)['status'] == 'closed')
            waiting = old and old.get('_needs_verification') and old['_retry_at'] > now
            if waiting or (terminal and (old.get('listing_signature') or listing_signature(old)) == record.get('listing_signature')):
                cache[record['id']] = {**{k: v for k, v in old.items() if not k.startswith('_')}, 'detail_reused': True}
            else:
                cache[record['id']] = verify_period(record)
        return cache[record['id']]
    checked = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for item in pool.map(verify, unique.values()):
            checked.append(item)
            if len(checked) % 100 == 0:
                print(f'[contestkorea] {kind}: details={len(checked)}/{len(unique)}', file=sys.stderr, flush=True)
    items = tuple(checked)
    unverified = sum(item.get('period_source') == 'unverified' for item in items)
    network = sum(item.get('verification_error') in ('network_error', 'provider_unavailable') for item in items)
    parse = sum(item.get('verification_error') == 'parse_error' or
                (item.get('period_source') == 'unverified' and not item.get('verification_error')) for item in items)
    unknown = sum(item.get('period_source') == 'unknown' for item in items)
    observations = (*skipped.values(), *items)
    eligible = tuple(item for item in items if not item.get('verification_error')
                     and item.get('period_source') not in ('unknown', 'unverified')
                     and not item.get('application_closed') and not item.get('application_cancelled')
                     and eligible_target(item['target'])
                     and period_status(item.get('verified_period') or item['period'], now)['status'] in ('open', 'upcoming'))
    network += category_network
    parse += category_parse + rejected
    incomplete = failed or rejected or network or parse
    status = 'error' if failed == len(codes) or (rejected and not unique) else 'partial' if incomplete else 'success'
    return Collection(eligible if eligible_only else items, status, len(codes), failed, rejected,
                      'collection_incomplete' if incomplete else None, unverified, network + parse,
                      fetched, len(eligible), unknown, parse, network, observations, limited, sum(bool(i.get('detail_reused')) for i in items))

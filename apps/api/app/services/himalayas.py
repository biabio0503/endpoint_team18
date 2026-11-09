"""Read-only Himalayas search; no persistence or model inference."""
import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SEARCH_URL = 'https://himalayas.app/jobs/api/search'
MAX_LIMIT = 100
TIMEOUT = 10
MAX_RETRY_WAIT = 3

# Each entry is a distinct role. Synonyms are direct; expansion roles are related.
ROLES = (
    ('Data Analyst', ('데이터 분석가', '데이터 애널리스트', '데이터 분석', 'data analyst', 'data analytics'), ('BI Analyst',), ('Data Scientist',)),
    ('Data Scientist', ('데이터 사이언티스트', '데이터 과학자', 'data scientist', 'data science'), (), ('Data Analyst',)),
    ('Backend Engineer', ('백엔드', '백 엔드', '서버 개발', 'backend', 'back-end', 'back end'), ('Backend Developer',), ()),
    ('Frontend Engineer', ('프론트엔드', '프론트 엔드', 'frontend', 'front-end', 'front end'), ('Frontend Developer',), ()),
    ('Machine Learning Engineer', ('머신러닝', '기계학습', 'machine learning', '인공지능', '인공 지능', 'ai model'), (), ('AI Engineer',)),
    ('Data Engineer', ('데이터 엔지니어', 'data engineer', 'data engineering'), (), ()),
    ('Cloud Engineer', ('클라우드', 'cloud engineer', 'cloud engineering'), (), ()),
    ('AI Engineer', ('ai 개발자', 'ai 엔지니어', 'ai engineer', 'artificial intelligence'), (), ('Machine Learning Engineer',)),
)


def _contains(text, term):
    if re.search(r'[가-힣]', term):
        return term.casefold() in text.casefold()
    # Ignore punctuation and spaces for variants like back-end and backend.
    normalized = re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()
    needle = re.sub(r'[^a-z0-9]+', ' ', term.casefold()).strip()
    return bool(needle and re.search(r'(?<![a-z0-9])' + re.escape(needle).replace(r'\ ', r'\s+') + r'(?![a-z0-9])', normalized))


def generate_search_keywords(career_goal, target_role=None):
    """Return keyword objects with their direct/related relation, or a reason."""
    text = (target_role or '').strip() or (career_goal or '').strip()
    if not text:
        return [], 'missing_input'
    # Handle natural descriptions where particles separate server and development.
    if not (target_role or '').strip() and '서버' in text and ('개발' in text or '데이터베이스' in text):
        text = '백엔드'
    for name, aliases, synonyms, related in ROLES:
        if any(_contains(text, alias) for alias in aliases) or _contains(text, name):
            return ([{'keyword': k, 'relation': relation} for relation, values in
                     (('direct', (name,) + synonyms), ('related', related)) for k in values][:3], None)
    # Fallback accepts a short English role, never an unknown Korean sentence.
    if (target_role or '').strip() and re.fullmatch(r"[A-Za-z][A-Za-z0-9 +./&'()-]{1,99}", text) and len(text.split()) <= 8 and re.search(r'\b(engineer|developer|analyst|scientist|designer|manager|architect|consultant|specialist|administrator|researcher|research|director|lead|writer|recruiter|accountant|marketer|product|devops|sre)\b', text, re.I):
        return [{'keyword': text, 'relation': 'direct'}], None
    return [], 'unmapped_role' if (target_role or '').strip() else 'unmapped_goal'


class _TextExtractor(HTMLParser):
    BLOCKS = {'p', 'div', 'br', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'tr', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(value):
    if not isinstance(value, str):
        return None
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r'[\t\r\f\v ]+', ' ', line).strip() for line in ''.join(parser.parts).split('\n')]
    return '\n'.join(line for line in lines if line)


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')
    except (OverflowError, OSError, ValueError):
        return None


def _source_url(guid):
    if not isinstance(guid, str):
        return None
    try:
        parsed = urlsplit(guid)
        if parsed.scheme == 'https' and parsed.netloc.lower() in ('himalayas.app', 'www.himalayas.app') and parsed.path.startswith('/companies/'):
            return guid
    except ValueError:
        pass
    return None


def _match(job, keywords):
    title = job.get('title') if isinstance(job.get('title'), str) else ''
    categories = job.get('categories') if isinstance(job.get('categories'), list) else []
    parents = job.get('parent_categories') if isinstance(job.get('parent_categories'), list) else []
    text = ' '.join([title] + [c for c in categories + parents if isinstance(c, str)])
    matches = [k['relation'] for k in keywords if _contains(text, k['keyword'])]
    return 'direct' if 'direct' in matches else 'related' if 'related' in matches else 'unverified'


def normalize_job(raw, keyword, keywords):
    description = raw.get('description')
    job = {'id': raw['guid'], 'source': 'Himalayas', 'source_url': _source_url(raw['guid']),
           'title': raw.get('title'), 'company': raw.get('companyName'), 'company_slug': raw.get('companySlug'),
           'categories': raw.get('categories'), 'parent_categories': raw.get('parentCategories'),
           'seniority': raw.get('seniority'), 'employment_type': raw.get('employmentType'),
           'description_html': description if isinstance(description, str) else None,
           'description_text': html_to_text(description), 'excerpt': raw.get('excerpt'),
           'published_at': _timestamp(raw.get('pubDate')), 'expires_at': _timestamp(raw.get('expiryDate')),
           'location_restrictions': raw.get('locationRestrictions'), 'timezone_restrictions': raw.get('timezoneRestrictions'),
           'application_link': raw.get('applicationLink'), 'matched_keywords': [keyword]}
    job['match_type'] = _match(job, keywords)
    return job


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SearchError(Exception):
    def __init__(self, code, status=None, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after


def _retry_delay(value):
    if value is None:
        return 1.0
    try:
        delay = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            delay = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, delay) if delay == delay and delay != float('inf') else None


def _request_page(keyword, page):
    headers = {'Accept': 'application/json', 'User-Agent': 'CareerRoadmap/1.0'}
    key = os.environ.get('HIMALAYAS_API_KEY', '').strip()
    if key:
        headers['Authorization'] = 'Bearer ' + key
    url = SEARCH_URL + '?' + urlencode({'q': keyword, 'page': page, 'sort': 'relevant'})
    opener = build_opener(_NoRedirect())
    for attempt in range(2):
        try:
            with opener.open(Request(url, headers=headers), timeout=TIMEOUT) as response:
                data = json.load(response)
            if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
                raise SearchError('invalid_response')
            if any(not isinstance(j, dict) or not isinstance(j.get('guid'), str) or not j['guid'].strip() for j in data['jobs']):
                raise SearchError('invalid_response')
            return data
        except HTTPError as exc:
            status = exc.code
            delay = _retry_delay(exc.headers.get('Retry-After')) if status == 429 else 1.0
            exc.close()
            if attempt == 0 and (status == 429 or 500 <= status <= 599) and delay is not None and delay <= MAX_RETRY_WAIT:
                time.sleep(delay)
                continue
            raise SearchError('http_' + str(status), status, delay if status == 429 else None) from None
        except (TimeoutError, socket.timeout):
            if attempt == 0:
                time.sleep(1)
                continue
            raise SearchError('timeout') from None
        except URLError as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            raise SearchError('timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'connection_error') from None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise SearchError('invalid_json') from None


def fetch_jobs(career_goal: str, target_role: str | None = None, limit: int = 20) -> dict:
    """Return a JSON-serializable search result, including per-keyword outcomes."""
    if not isinstance(career_goal, str) or (target_role is not None and not isinstance(target_role, str)):
        raise ValueError('career_goal and target_role must be strings')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be an integer between 1 and {MAX_LIMIT}')
    keywords, reason = generate_search_keywords(career_goal, target_role)
    result = {'source': 'Himalayas', 'source_url': 'https://himalayas.app', 'market_scope': 'global_remote',
              'career_goal': career_goal, 'target_role': target_role, 'search_keywords': [k['keyword'] for k in keywords],
              'keyword_details': keywords, 'status': 'error' if reason else 'success', 'total_collected': 0,
              'retrieved_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
              'jobs': [], 'searches': [], 'errors': []}
    if reason:
        result['errors'].append({'code': reason})
        return result
    jobs = {}
    success_pages = 0
    blocked = False
    for entry in keywords:
        keyword = entry['keyword']
        search = {'keyword': keyword, 'relation': entry['relation'], 'status': 'success', 'pages_succeeded': 0, 'received_count': 0}
        result['searches'].append(search)
        if blocked:
            search['status'] = 'skipped'
            result['errors'].append({'keyword': keyword, 'code': 'rate_limit_active'})
            continue
        for page in (1, 2):
            if page > 1 and len(jobs) >= limit:
                break
            try:
                data = _request_page(keyword, page)
            except SearchError as exc:
                search['status'] = 'partial' if search['pages_succeeded'] else 'error'
                error = {'keyword': keyword, 'page': page, 'code': exc.code}
                if exc.status is not None:
                    error['http_status'] = exc.status
                if exc.retry_after is not None:
                    error['retry_after'] = exc.retry_after
                result['errors'].append(error)
                if exc.status == 429:
                    blocked = True
                break
            success_pages += 1
            search['pages_succeeded'] += 1
            search['received_count'] += len(data['jobs'])
            for raw in data['jobs']:
                guid = raw['guid']
                if guid in jobs:
                    if keyword not in jobs[guid]['matched_keywords']:
                        jobs[guid]['matched_keywords'].append(keyword)
                elif len(jobs) < limit:
                    jobs[guid] = normalize_job(raw, keyword, keywords)
            if not data['jobs']:
                break
    result['jobs'] = list(jobs.values())
    result['total_collected'] = len(jobs)
    if result['errors']:
        result['status'] = 'partial' if success_pages else 'error'
    return result

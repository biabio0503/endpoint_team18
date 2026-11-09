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
from services.job_relevance import classify_job, target_context

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
    """A specific title role is required; broad categories cannot override it."""
    title = job.get('title') if isinstance(job.get('title'), str) else ''
    # Prefer related over a shorter, overlapping direct phrase when both occur.
    matches = [entry for entry in keywords if _contains(title, entry['keyword'])]
    # Dynamic roles also cover titles such as "Engineer, Machine Learning" and
    # "Back-end Engineer". Require every whole role token in the title, never
    # infer relevance merely because the search API returned a job.
    def tokens(value):
        value = re.sub(r'\b(back|front)[ -]+end\b', r'\1end', value.casefold())
        return set(re.findall(r'[a-z0-9]+', value))
    title_tokens = tokens(title)
    matches += [entry for entry in keywords if entry not in matches and len(tokens(entry['keyword'])) >= 2
                and tokens(entry['keyword']) <= title_tokens]
    if not matches:
        return 'unverified', 'no_title_role_match'
    longest = max(matches, key=lambda entry: len(entry['keyword']))
    token_match = not _contains(title, longest['keyword'])
    categories = list(job.get('categories')) if isinstance(job.get('categories'), list) else []
    categories += (job.get('parent_categories') if isinstance(job.get('parent_categories'), list) else [])
    corroborated = any(isinstance(value, str) and _contains(value, longest['keyword']) for value in categories)
    return longest['relation'], ('title_role_tokens_match' if token_match else
                                 'title_and_category_role_match' if corroborated else 'title_role_match')


def _seniority_signals(text):
    signals = set()
    for group, terms in (
        ('entry', ('intern', 'internship', 'junior', 'entry level', 'graduate')),
        ('mid', ('mid level', 'mid', 'intermediate')),
        ('senior', ('senior', 'staff', 'principal', 'lead', 'director', 'manager', 'executive')),
    ):
        if any(_contains(text, term) for term in terms):
            signals.add(group)
    return signals


def seniority_group(seniority, title):
    """Conflicting, mixed or unknown explicit levels are not guessed."""
    values = [seniority] if isinstance(seniority, str) else seniority if isinstance(seniority, list) else []
    values = [value for value in values if isinstance(value, str) and value.strip()]
    explicit = set()
    for value in values:
        signals = _seniority_signals(value)
        if not signals:
            return 'unknown'
        explicit.update(signals)
    title_signals = _seniority_signals(title if isinstance(title, str) else '')
    if len(explicit) > 1 or len(title_signals) > 1:
        return 'unknown'
    if explicit and title_signals and explicit != title_signals:
        return 'unknown'
    return next(iter(explicit or title_signals), 'unknown')


def _exclusion_reasons(job, now):
    reasons = []
    if job['match_type'] == 'unverified':
        reasons.append('unverified')
    reasons.extend(job.get('relevance', {}).get('reasons', []))
    if not isinstance(job.get('description_text'), str) or not job['description_text'].strip():
        reasons.append('missing_description')
    if job.get('expires_at'):
        try:
            if datetime.fromisoformat(job['expires_at'].replace('Z', '+00:00')) < now:
                reasons.append('expired')
        except (TypeError, ValueError):
            pass
    return reasons


def select_jobs(candidates, keywords, limit, now):
    """Select deterministically from unique normalized jobs, returning audit counts."""
    # The collector deduplicates too; enforce identity at this public boundary.
    candidates = list({job['id']: job for job in candidates}.values())
    eligible = []
    excluded = {'unverified': 0, 'missing_description': 0, 'expired': 0}
    excluded_count = 0
    for job in candidates:
        reasons = _exclusion_reasons(job, now)
        job['analysis_eligible'] = not reasons
        job['analysis_reasons'] = reasons or ['eligible']
        job['source_verified'] = bool(job.get('source_url'))
        if reasons:
            excluded_count += 1
            for reason in reasons:
                excluded[reason] = excluded.get(reason, 0) + 1
        else:
            eligible.append(job)
    direct = [j for j in eligible if j['match_type'] == 'direct']
    related = [j for j in eligible if j['match_type'] == 'related']
    # Reserve up to 20% for related jobs when direct candidates are abundant.
    related_target = min(len(related), limit // 5)
    direct_target = min(len(direct), limit - related_target)
    related_target = min(len(related), limit - direct_target)
    selected = []
    keyword_counts = {entry['keyword']: 0 for entry in keywords}
    company_counts = {}
    senior_count = 0

    def take(pool, amount):
        nonlocal senior_count
        pool = list(pool)
        for _ in range(amount):
            if not pool:
                break
            # Use the same global soft senior cap across both role categories.
            if any(j['seniority_group'] == 'entry' for j in pool):
                group = 'entry'
            elif any(j['seniority_group'] == 'mid' for j in pool):
                group = 'mid'
            elif senior_count < limit // 4 and any(j['seniority_group'] == 'senior' for j in pool):
                group = 'senior'
            elif any(j['seniority_group'] == 'unknown' for j in pool):
                group = 'unknown'
            else:
                group = 'senior'
            group_jobs = [j for j in pool if j['seniority_group'] == group]
            def choices(job):
                return [k for k in job['matched_keywords'] if k in keyword_counts]
            def key(job):
                hits = choices(job)
                least_used = min((keyword_counts[k] for k in hits), default=0)
                company = job.get('company_slug') or job.get('company')
                company_key = company.casefold().strip() if isinstance(company, str) and company.strip() else None
                return least_used, company_counts.get(company_key, 0) if company_key else 0
            chosen = min(group_jobs, key=key)  # input order is the final tie-breaker
            hits = choices(chosen)
            if hits:
                chosen_keyword = min(hits, key=lambda k: (keyword_counts[k], list(keyword_counts).index(k)))
                keyword_counts[chosen_keyword] += 1
            company = chosen.get('company_slug') or chosen.get('company')
            if isinstance(company, str) and company.strip():
                company_key = company.casefold().strip()
                company_counts[company_key] = company_counts.get(company_key, 0) + 1
            if chosen['seniority_group'] == 'senior':
                senior_count += 1
            selected.append(chosen)
            pool.remove(chosen)

    take(direct, direct_target)
    take(related, related_target)
    distribution = {group: sum(job['seniority_group'] == group for job in selected)
                    for group in ('entry', 'mid', 'senior', 'unknown')}
    summary = {'unique_candidates': len(candidates), 'eligible_candidates': len(eligible),
               'excluded_count': excluded_count, 'excluded_by_reason': excluded,
               'unverified_excluded': excluded['unverified'],
               'source_unverified_candidates': sum(not job['source_verified'] for job in candidates),
               'eligible_not_selected': len(eligible) - len(selected),
               'selected_count': len(selected),
               'direct_count': sum(job['match_type'] == 'direct' for job in selected),
               'related_count': sum(job['match_type'] == 'related' for job in selected),
               'seniority_distribution': distribution}
    return selected, summary


def normalize_job(raw, keyword, keywords, target=None):
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
    job['match_type'], job['match_reason'] = _match(job, keywords)
    job['relevance'] = classify_job(job, target or target_context(keywords=keywords))
    job['match_type'] = job['relevance']['match_type']
    job['seniority_group'] = seniority_group(job['seniority'], job['title'])
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
    _validate_inputs(career_goal, target_role, limit)
    keywords, reason = generate_search_keywords(career_goal, target_role)
    return _fetch_jobs(career_goal, target_role, limit, keywords, reason)


def fetch_jobs_with_keywords(career_goal, target_role, keywords, limit=20):
    """Collect using validated model keywords, without invoking the legacy dictionary."""
    from services.job_skill_schemas import RoleInterpretation
    _validate_inputs(career_goal, target_role, limit)
    # Apply the same relation, length, dedup and direct-keyword invariants at this boundary.
    checked = RoleInterpretation.model_validate({
        'status': 'success', 'canonical_role': next((k['keyword'] for k in keywords if k.get('relation') == 'direct'), None),
        'search_keywords': keywords, 'clarification_message': None})
    return _fetch_jobs(career_goal, target_role, limit,
                       [entry.model_dump() for entry in checked.search_keywords], None)


def _validate_inputs(career_goal, target_role, limit):
    if not isinstance(career_goal, str) or (target_role is not None and not isinstance(target_role, str)):
        raise ValueError('career_goal and target_role must be strings')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be an integer between 1 and {MAX_LIMIT}')


def _fetch_jobs(career_goal, target_role, limit, keywords, reason):
    now = datetime.now(timezone.utc)
    target = target_context(career_goal, target_role, keywords)
    result = {'source': 'Himalayas', 'source_url': 'https://himalayas.app', 'market_scope': 'global_remote',
              'career_goal': career_goal, 'target_role': target_role, 'search_keywords': [k['keyword'] for k in keywords],
              'keyword_details': keywords, 'status': 'error' if reason else 'success', 'total_collected': 0,
              'retrieved_at': now.isoformat().replace('+00:00', 'Z'),
              'jobs': [], 'searches': [], 'errors': []}
    jobs = {}
    success_pages = 0
    blocked = False
    if reason:
        result['errors'].append({'code': reason})
    else:
        for entry in keywords:
            result['searches'].append({'keyword': entry['keyword'], 'relation': entry['relation'], 'status': 'success',
                                       'pages_succeeded': 0, 'received_count': 0})
        # First gather all first pages; only fetch page two if eligible candidates are insufficient.
        for page in (1, 2):
            if page == 2:
                eligible = [j for j in jobs.values() if not _exclusion_reasons(j, now)]
                direct_count = sum(j['match_type'] == 'direct' for j in eligible)
                related_count = sum(j['match_type'] == 'related' for j in eligible)
                direct_target = limit - min(related_count, limit // 5)
                if len(eligible) >= limit and direct_count >= direct_target:
                    break
            for entry, search in zip(keywords, result['searches']):
                keyword = entry['keyword']
                if page == 2 and (search['status'] != 'success' or not search['received_count']):
                    continue
                if blocked:
                    if page == 1:
                        search['status'] = 'skipped'
                        result['errors'].append({'keyword': keyword, 'code': 'rate_limit_active'})
                    continue
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
                    continue
                success_pages += 1
                search['pages_succeeded'] += 1
                search['received_count'] += len(data['jobs'])
                for raw in data['jobs']:
                    guid = raw['guid']
                    if guid in jobs:
                        if keyword not in jobs[guid]['matched_keywords']:
                            jobs[guid]['matched_keywords'].append(keyword)
                    else:
                        jobs[guid] = normalize_job(raw, keyword, keywords, target)
    result['jobs'], summary = select_jobs(list(jobs.values()), keywords, limit, now)
    summary['total_candidates'] = sum(search['received_count'] for search in result['searches'])
    summary['duplicate_occurrences'] = summary['total_candidates'] - summary['unique_candidates']
    result['selection_summary'] = summary
    summary['decisions'] = [{key: job.get(key) for key in
                             ('id', 'title', 'source_url', 'match_type', 'match_reason', 'relevance', 'analysis_eligible', 'analysis_reasons')}
                            for job in jobs.values()]
    result['total_collected'] = len(result['jobs'])
    if result['errors']:
        result['status'] = 'partial' if success_pages else 'error'
    return result

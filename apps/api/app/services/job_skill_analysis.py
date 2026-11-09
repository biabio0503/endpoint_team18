"""Ephemeral job sample analysis: model output -> source validation -> unique-job counts."""
from collections import Counter
import re
import unicodedata

from services.gemini import GeminiError
from services.gemini_jobs import extract_job_skills, generate_job_keywords
from services.himalayas import fetch_jobs_with_keywords
from services.job_relevance import evidence_context

ANALYSIS_VERSION = 'job-skills-v2'
MAX_JOBS = 20
BATCH_SIZE = 5
MAX_DESCRIPTION_CHARS = 40000
MAX_BATCH_CHARS = 120000

# Explicit aliases only; no stemming or substring merging (Java != JavaScript, SQL != PostgreSQL).
TECHNOLOGIES = (
    ('Python', 'programming_language', ('Python3', 'Python 3')),
    ('Java', 'programming_language', ()),
    ('JavaScript', 'programming_language', ('JS',)),
    ('TypeScript', 'programming_language', ('TS',)),
    ('SQL', 'database_query_language', ()),
    ('PostgreSQL', 'database', ('Postgres',)),
    ('MongoDB', 'database', ('Mongo DB',)),
    ('Redis', 'database', ()),
    ('AWS', 'cloud', ('Amazon Web Services',)),
    ('GCP', 'cloud', ('Google Cloud', 'Google Cloud Platform')),
    ('Azure', 'cloud', ('Microsoft Azure',)),
    ('React', 'framework', ('React.js', 'ReactJS', 'React JS')),
    ('Spring Boot', 'framework', ('SpringBoot',)),
    ('FastAPI', 'framework', ('Fast API',)),
    ('Docker', 'devops', ()),
    ('Kubernetes', 'devops', ('K8s',)),
    ('Git', 'development_tool', ()),
    ('Excel', 'development_tool', ('Microsoft Excel', 'MS Excel')),
    ('Power BI', 'data_ai', ('PowerBI', 'Microsoft Power BI', 'MS Power BI')),
    ('Tableau', 'data_ai', ()),
    ('CAD', 'development_tool', ()),
    ('CATIA', 'development_tool', ()),
    ('SolidWorks', 'development_tool', ('Solid Works',)),
    ('AutoCAD', 'development_tool', ('Auto CAD',)),
    ('CISSP', 'other', ()),
    ('PyTorch', 'data_ai', ('Py Torch',)),
    ('TensorFlow', 'data_ai', ('Tensor Flow',)),
    ('Spark', 'data_ai', ('Apache Spark',)),
    ('CI/CD', 'devops', ('CI / CD', 'CI CD', 'continuous integration and continuous delivery',
                         'continuous integration/continuous deployment')),
)


def _key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


ALIASES = {_key(alias): (name, category, (name,) + aliases)
           for name, category, aliases in TECHNOLOGIES for alias in (name,) + aliases}


def normalize_skill(name, category):
    known = ALIASES.get(_key(name))
    return (known[0], known[1]) if known else (' '.join(unicodedata.normalize('NFKC', name).split()), category)


def _skill_in_quote(name, quote):
    aliases = ALIASES.get(_key(name), (name, None, (name,)))[2]
    return any(re.search(r'(?<!\w)' + re.escape(_key(alias)) + r'(?!\w)', _key(quote)) for alias in aliases)


def _requirement(kind, quote):
    # An explicit label needs explicit evidence. Ambiguous model labels are not
    # silently promoted to mandatory requirements; the raw label remains available.
    if kind not in ('required', 'preferred'):
        return kind
    optional = re.search(r'\b(preferred|preferably|nice[ -]to[ -]have|plus|bonus|optional|desirable)\b|우대|선호', quote, re.I)
    mandatory = re.search(r'\b(required|requirements?|must|mandatory|essential|minimum|qualifications?|need to)\b|필수|자격요건', quote, re.I)
    if optional and mandatory:
        return 'unknown'
    if kind == 'preferred':
        return 'preferred' if optional else 'unknown'
    return 'preferred' if optional else 'required' if mandatory else 'unknown'


def verify_skills(job, extracted):
    verified, rejected = [], []
    for item in extracted:
        raw = item.model_dump()
        start = job['description_text'].find(item.evidence_text)
        reason = 'evidence_not_in_source' if start < 0 else None
        if not reason and (item.category != 'technical_competency' or _key(item.name) in ALIASES) and not _skill_in_quote(item.name, item.evidence_text):
            reason = 'skill_not_in_evidence'
        if reason:
            rejected.append({'skill': raw, 'reason': reason})
            continue
        name, category = normalize_skill(item.name, item.category)
        section, local, actionable = evidence_context(
            job['description_text'], start, start + len(item.evidence_text),
            lambda clause: _skill_in_quote(name, clause) or (category == 'technical_competency' and _key(name) not in ALIASES))
        kind = _requirement(item.requirement_type, local)
        if not actionable:
            kind = 'mentioned'
        elif section in ('required', 'preferred'):
            kind = _requirement(section, section + ': ' + local)
        verified.append({**raw, 'name': name, 'category': category,
                         'requirement_type': kind, 'evidence_section': section,
                         'recommendation_eligible': actionable,
                         'relevance_reason': 'role_requirement_or_duty' if actionable else 'context_or_negated_requirement',
                         'model_requirement_type': item.requirement_type,
                         'evidence_start': start, 'evidence_end': start + len(item.evidence_text),
                         'evidence_verified': True})
    return verified, rejected


def aggregate_skills(analyses):
    successful = {item['job_id']: item for item in analyses if item['status'] == 'success'}
    groups = {}
    for job in successful.values():
        for skill in job['verified_skills']:
            name, category = normalize_skill(skill['name'], skill['category'])
            key = _key(name)
            group = groups.setdefault(key, {'name': name, 'category': category, 'jobs': {}, 'support': {}, 'evidence': []})
            group['jobs'].setdefault(job['job_id'], set()).add(skill['requirement_type'])
            if skill.get('recommendation_eligible', True):
                group['support'].setdefault(job['job_id'], set()).add(skill['requirement_type'])
            evidence = {key: skill[key] for key in ('requirement_type', 'evidence_text', 'evidence_start', 'evidence_end')}
            evidence.update({k: skill[k] for k in ('evidence_section', 'recommendation_eligible', 'relevance_reason') if k in skill})
            evidence.update(job_id=job['job_id'], source_url=job['source_url'], title=job['title'],
                            match_type=job['match_type'], seniority_group=job['seniority_group'])
            if evidence not in group['evidence']:
                group['evidence'].append(evidence)
    output = []
    for group in groups.values():
        jobs = group.pop('jobs')
        support = group.pop('support')
        # Per-job counters are exclusive. Preserve all original statements in evidence.
        kinds = Counter(next(kind for kind in ('required', 'preferred', 'mentioned', 'unknown') if kind in values)
                        for values in jobs.values())
        support_kinds = Counter(next(kind for kind in ('required', 'preferred', 'mentioned', 'unknown') if kind in values)
                                for values in support.values())
        output.append({**group, 'mentioned_job_count': len(jobs),
                       'recommendation_eligible': bool(support),
                       'supporting_job_count': len(support),
                       'supporting_direct_job_count': sum(successful[j]['match_type'] == 'direct' for j in support),
                       'supporting_required_job_count': support_kinds['required'],
                       'supporting_preferred_job_count': support_kinds['preferred'],
                       'priority_reason': (f'직무 업무·요건 근거 {len(support)}개 독립 공고; 필수 {support_kinds["required"]}, 우대 {support_kinds["preferred"]}.'
                                           if support else '회사 소개·주변 맥락 또는 부정된 요건만 확인되어 핵심 추천에서 제외합니다.'),
                       'single_job_notice': '1개 독립 공고에서만 확인했습니다. 일반화하지 말고 원문과 요구 수준을 확인해 주세요.' if len(jobs) == 1 else None,
                       'required_job_count': kinds['required'], 'preferred_job_count': kinds['preferred'],
                       'mentioned_only_job_count': kinds['mentioned'], 'unknown_job_count': kinds['unknown'],
                       'mention_frequency': len(jobs) / len(successful),
                       'direct_job_count': sum(successful[j]['match_type'] == 'direct' for j in jobs),
                       'related_job_count': sum(successful[j]['match_type'] == 'related' for j in jobs),
                       'seniority_distribution': {level: sum(successful[j]['seniority_group'] == level for j in jobs)
                                                 for level in ('entry', 'mid', 'senior', 'unknown')}})
    return sorted(output, key=skill_priority)


def skill_priority(item, status=None):
    """Explainable lexicographic order, not an employability or mastery score."""
    return (not item.get('recommendation_eligible', True),
            -item.get('supporting_direct_job_count', item.get('direct_job_count', 0)),
            -item.get('supporting_job_count', item.get('mentioned_job_count', 0)),
            -item.get('supporting_required_job_count', item.get('required_job_count', 0)),
            -item.get('supporting_preferred_job_count', item.get('preferred_job_count', 0)),
            {'confirmed_experience': 0, 'no_experience': 1, 'document_supported': 2}.get(status, 3),
            _key(item.get('name', item.get('skill_name', ''))))


def analyze_job_skills(career_goal, target_role=None, limit=MAX_JOBS):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_JOBS:
        raise ValueError('Analysis limit must be between 1 and 20')
    result = {'status': 'error', 'analysis_version': ANALYSIS_VERSION, 'career_goal': career_goal, 'target_role': target_role,
              'canonical_role': None, 'search_keywords': [], 'keyword_details': [],
              'source': 'Himalayas', 'source_url': 'https://himalayas.app', 'market_scope': 'global_remote',
              'retrieved_at': None, 'searches': [], 'selection_summary': None,
              'collection_summary': {'status': 'not_started', 'selected_jobs': 0},
              'analysis_summary': {'analyzed_jobs': 0, 'failed_jobs': 0, 'skipped_jobs': 0,
                                   'rejected_skill_count': 0, 'batch_count': 0, 'planned_batch_count': 0},
              'analysis_limits': {'max_jobs': MAX_JOBS, 'batch_size': BATCH_SIZE,
                                  'max_description_chars': MAX_DESCRIPTION_CHARS, 'max_batch_chars': MAX_BATCH_CHARS},
              'job_analyses': [], 'skills': [], 'errors': []}
    try:
        interpretation = generate_job_keywords(career_goal, target_role)
    except GeminiError as exc:
        result['errors'].append({'stage': 'keywords', 'code': exc.code, 'message': exc.message})
        return result
    result['canonical_role'] = interpretation.canonical_role
    if interpretation.status == 'needs_clarification':
        result.update(status='needs_clarification', clarification_message=interpretation.clarification_message)
        return result
    keywords = [entry.model_dump() for entry in interpretation.search_keywords]
    collection = fetch_jobs_with_keywords(career_goal, target_role, keywords, limit)
    for key in ('search_keywords', 'keyword_details', 'retrieved_at', 'searches', 'selection_summary'):
        result[key] = collection[key]
    result['collection_summary'] = {'status': collection['status'], 'selected_jobs': len(collection['jobs'])}
    result['sample_notice'] = (f'목표 직무·도메인과 원문 조건을 통과한 공고는 {len(collection["jobs"])}개입니다. '
                               f'요청한 {limit}개보다 적으며 다른 직무로 채우지 않았습니다. 작은 해외 원격근무 표본입니다.'
                               if len(collection['jobs']) < limit else None)
    result['errors'].extend(dict(error, stage='collection') for error in collection['errors'])
    if not collection['jobs']:
        result['status'] = 'no_jobs' if collection['status'] == 'success' else 'error'
        return result

    # Never truncate. Oversized documents are explicitly skipped with their measured length.
    batches, batch, chars = [], [], 0
    records = {}
    for job in collection['jobs']:
        if job['id'] in records:
            continue
        record = {key: job.get(key) for key in ('title', 'source_url', 'match_type', 'seniority_group')}
        record.update(job_id=job['id'], status='pending', model_skills=[], verified_skills=[], rejected_skills=[])
        records[job['id']] = record
        length = len(job['description_text'])
        if length > MAX_DESCRIPTION_CHARS:
            record.update(status='skipped', reason='description_too_long', description_chars=length,
                          max_description_chars=MAX_DESCRIPTION_CHARS, analyzed_char_range=None)
            result['errors'].append({'stage': 'extraction', 'code': 'description_too_long', 'job_id': job['id']})
            continue
        if batch and (len(batch) == BATCH_SIZE or chars + length > MAX_BATCH_CHARS):
            batches.append(batch)
            batch, chars = [], 0
        batch.append(job)
        chars += length
    if batch:
        batches.append(batch)
    result['analysis_summary']['planned_batch_count'] = len(batches)
    rate_limited = False
    for index, jobs in enumerate(batches):
        if rate_limited:
            for job in jobs:
                records[job['id']].update(status='skipped', reason='gemini_rate_limit_active', analyzed_char_range=None)
            result['errors'].append({'stage': 'extraction', 'batch_index': index, 'code': 'gemini_rate_limit_active',
                                     'job_ids': [job['id'] for job in jobs]})
            continue
        result['analysis_summary']['batch_count'] += 1
        try:
            extraction = extract_job_skills(jobs)
        except GeminiError as exc:
            rate_limited = exc.code == 'gemini_rate_limited'
            for job in jobs:
                records[job['id']].update(status='failed', reason=exc.code)
            result['errors'].append({'stage': 'extraction', 'batch_index': index, 'code': exc.code,
                                     'message': exc.message, 'job_ids': [job['id'] for job in jobs]})
            continue
        expected = {job['id'] for job in jobs}
        counts = Counter(item.job_id for item in extraction.jobs)
        for job_id in counts.keys() - expected:
            # Do not echo invented identifiers or quotes into confirmed results.
            result['errors'].append({'stage': 'validation', 'batch_index': index, 'code': 'unexpected_job_id'})
        extracted = {item.job_id: item for item in extraction.jobs if item.job_id in expected}
        for job in jobs:
            record = records[job['id']]
            if counts[job['id']] != 1:
                reason = 'missing_job_result' if not counts[job['id']] else 'duplicate_job_result'
                record.update(status='failed', reason=reason)
                result['errors'].append({'stage': 'validation', 'code': reason, 'job_id': job['id']})
                continue
            skills = extracted[job['id']].skills
            verified, rejected = verify_skills(job, skills)
            record.update(status='success', model_skills=[item.model_dump() for item in skills],
                          verified_skills=verified, rejected_skills=rejected,
                          analyzed_char_range=[0, len(job['description_text'])])
            if rejected:
                result['errors'].append({'stage': 'validation', 'code': 'skills_rejected',
                                         'job_id': job['id'], 'count': len(rejected)})
                # An all-hallucinated result must not inflate the successful-job denominator.
                if not verified:
                    record.update(status='failed', reason='no_verified_skills')
    result['job_analyses'] = list(records.values())
    counts = Counter(record['status'] for record in records.values())
    result['analysis_summary'].update(analyzed_jobs=counts['success'], failed_jobs=counts['failed'],
                                      skipped_jobs=counts['skipped'],
                                      rejected_skill_count=sum(len(r['rejected_skills']) for r in records.values()))
    result['skills'] = aggregate_skills(result['job_analyses'])
    if counts['success'] < len(collection['jobs']):
        result['sample_notice'] = (result['sample_notice'] or '') + f' 선정 공고 중 기술 분석에 성공한 표본은 {counts["success"]}개입니다. 빈도의 분모는 성공 공고만 사용합니다.'
    result['status'] = ('error' if not counts['success'] else 'partial'
                        if result['errors'] or counts['failed'] or counts['skipped'] else 'success')
    return result

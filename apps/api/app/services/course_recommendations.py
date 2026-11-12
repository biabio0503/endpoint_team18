"""Server-owned course ranking and source-grounded explanations."""
import re
import unicodedata
from functools import lru_cache

from services.job_skill_analysis import ALIASES, normalize_skill

RULES_VERSION = 'course-evidence-v6-compound-spans'

# One vocabulary is used for explicit goals, job skills and related candidates.
# Keep overlapping language names distinct when matching free text.
COURSE_ALIASES = {
    **ALIASES,
    **{alias.casefold(): (name, 'other', variants)
       for name, variants in (
           ('JavaScript', ('JavaScript', 'JS', 'Java script', '자바스크립트')),
           ('C', ('C', 'C언어', 'C 언어')),
           ('C++', ('C++', 'C plus plus', '씨플플')),
           ('C#', ('C#', 'C sharp', '씨샵')),
           ('CNN', ('CNN', 'convolutional neural network', 'convolutional neural networks', '합성곱 신경망')),
       ) for alias in variants},
}
PROGRAMMING_GOALS = ('프로그래밍', '개발', '코딩', 'Python', 'Java', 'JavaScript',
                     'TypeScript', 'C', 'C++', 'C#', 'pandas')


def available_courses(courses):
    return {str(c['course_id']): c for c in courses if not c['is_completed'] and not c.get('equivalent_completed')}


def selected_courses(ids, courses, review_status):
    allowed = available_courses(courses)
    result, seen = [], set()
    for course_id in ids:
        if course_id in allowed and course_id not in seen and not set(allowed[course_id].get('verified_equivalent_ids', [])) & seen:
            course = dict(allowed[course_id])
            course.pop('description_text', None)
            course.pop('_keyword_sources', None)
            course['is_completed'] = False
            course['completion_state'] = 'not_selected_in_reviewed_catalog' if review_status in ('confirmed', 'partial') else 'unconfirmed'
            result.append(course)
            seen.add(course_id)
    return result


def _key(value):
    key = ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()
    return COURSE_ALIASES.get(key, (normalize_skill(value, 'other')[0],))[0].casefold()


def _variants(keyword):
    key = ' '.join(unicodedata.normalize('NFKC', keyword).split()).casefold()
    return COURSE_ALIASES.get(key, (keyword, None, (keyword,)))[2]


@lru_cache(maxsize=2048)
def _pattern(keyword):
    terms = [re.escape(unicodedata.normalize('NFKC', v).casefold()).replace(r'\ ', r'\s*')
             for v in sorted(_variants(keyword), key=len, reverse=True)]
    return re.compile(r'(?<![a-z0-9_+#])(?:' + '|'.join(terms) + r')(?![a-z0-9_+#])')


_CLAUSE_BOUNDARY = re.compile(
    r'[.!?。;\n]|(?:배웠|배우|학습했|학습하|공부했|공부하|익혔|익히|알고\s*있|경험(?:이|은|을)?\s*(?:있|보유))'
)


@lru_cache(maxsize=2048)
def _compound_patterns(keyword):
    """Find ordered Korean components with particles or short intervening phrases."""
    words = keyword.split()
    if len(words) < 2 or not all(re.fullmatch(r'[가-힣]{2,}', word) for word in words):
        return ()
    def pattern(parts):
        body = r'(.{0,40}?)'.join(map(re.escape, parts))
        return re.compile(r'(?=(?<![a-z0-9_+#])(' + body + r')(?![a-z0-9_+#]))')
    patterns = [pattern(words)]
    # An action can be described with its object while omitting a middle modifier.
    if len(words) >= 3:
        patterns.append(pattern((words[0], words[-1])))
    return tuple(patterns)


def _keyword_occurrences(keyword, normalized):
    occurrences = {(match.start(), match.end(), ((match.start(), match.end()),))
                   for match in _pattern(keyword).finditer(normalized)}
    for pattern in _compound_patterns(keyword):
        for match in pattern.finditer(normalized):
            if all(not _CLAUSE_BOUNDARY.search(gap) for gap in match.groups()[1:]):
                start, end = match.span(1)
                boundaries = [start]
                for group in range(2, len(match.groups()) + 1):
                    boundaries.extend(match.span(group))
                boundaries.append(end)
                parts = tuple((boundaries[i], boundaries[i + 1])
                              for i in range(0, len(boundaries), 2) if boundaries[i] < boundaries[i + 1])
                occurrences.add((start, end, parts))
    return sorted(occurrences)


def _matches(keyword, text):
    return bool(keyword and text and _keyword_occurrences(keyword, unicodedata.normalize('NFKC', text).casefold()))


@lru_cache(maxsize=512)
def _goal_mentions(goal, keywords=()):
    """Resolve aliases and catalog keywords by longest span, retaining separate mentions."""
    normalized = unicodedata.normalize('NFKC', goal).casefold()
    candidates = []
    names = {entry[0] for entry in COURSE_ALIASES.values()} | set(keywords)
    for name in names:
        for start, end, parts in _keyword_occurrences(name, normalized):
            candidates.append((start, end, _key(name), parts))
    accepted = []
    for start, end, key, parts in sorted(candidates, key=lambda m: (-(m[1] - m[0]), -sum(b - a for a, b in m[3]), m[0], m[2])):
        if not any(a < d and c < b for a, b in parts for _, _, _, other_parts in accepted for c, d in other_parts):
            accepted.append((start, end, key, parts))
    return normalized, sorted((start, end, key) for start, end, key, _ in accepted)


def _goal_mention_states(goal, keywords):
    normalized, mentions = _goal_mentions(goal, tuple(sorted(set(keywords))))
    past = []
    for index, (_, end, _) in enumerate(mentions):
        next_start = next((start for start, _, _ in mentions[index + 1:] if start >= end), len(normalized))
        context = normalized[end:next_start].split('.')[0]
        # A negated experience ("경험 없음") is not past experience.
        past.append(bool(re.match(r'\s*(?:은|는|을|를|이|가|의|도)?\s*(?:이미\s*)?(?:배웠|학습했|공부했|익혔|알고\s*있|경험(?:이|은|을)?\s*(?:있|보유))', context)))
    # A conjunction directly joining mentions shares the last mention's predicate.
    for index in range(len(mentions) - 2, -1, -1):
        gap = normalized[mentions[index][1]:mentions[index + 1][0]]
        if past[index + 1] and re.fullmatch(r'\s*(?:(?:와|과|하고|랑|이랑|및|,|·|/|와\s*같은)\s*)+', gap):
            past[index] = True
    states = {}
    for (_, _, key), is_past in zip(mentions, past):
        states.setdefault(key, []).append(is_past)
    return states


def _goal_learning_match(keyword, goal, states):
    if not _matches(keyword, goal):
        return False
    key = _key(keyword)
    return key in states and not all(states[key])


def rank_courses(profile, courses, review_status, skills=()):
    goal = ' '.join(str(profile.get(k) or '') for k in ('career_goal', 'target_role'))
    job = [s['skill_name'] for s in skills if s.get('job_requirement', {}).get('recommendation_eligible', True)]
    programming_goal = any(_matches(term, goal) for term in PROGRAMMING_GOALS)
    ranked = []
    keywords = [k['keyword'] for course in courses
                for source in (course.get('_keyword_sources') or [course])
                for k in source.get('keywords', []) if k.get('keyword_role') == 'learning']
    states = _goal_mention_states(goal, keywords + job)
    for course in available_courses(courses).values():
        description = course.get('description_text') or ''
        sources = course.get('_keyword_sources') or [course]
        member_ids = set(course.get('member_course_ids') or [course['course_id']])
        evidence = [{**k, 'source_course_id': source['course_id']}
                    for source in sources if source.get('course_id') in member_ids
                    for k in source.get('keywords', []) if (k.get('evidence_text') or '').strip()
                    and k['evidence_text'] in (source.get('description_text') or '')]
        learning = [k for k in evidence if k['keyword_role'] == 'learning']
        direct_goal = [k for k in learning if _goal_learning_match(k['keyword'], goal, states)]
        direct_job = [k for k in learning
                      if any(_key(k['keyword']) == _key(name) for name in job)
                      and not (_key(k['keyword']) in states and all(states[_key(k['keyword'])]))]
        matching = direct_goal or direct_job
        foundation = any(_matches(k['keyword'], '프로그래밍 기초') for k in learning) and programming_goal
        if matching:
            no_experience = any(s.get('student_status') == 'no_experience' and
                                any(_key(k['keyword']) == _key(s['skill_name']) for k in matching) for s in skills)
            kind, priority = 'direct', (0, 0 if direct_goal else 1, 0 if no_experience else 1)
            selected = matching
        elif foundation:
            kind, priority = 'foundation', (1, 0, 0)
            selected = [k for k in learning if _matches(k['keyword'], '프로그래밍 기초')]
        else:
            # A mention as an example or prerequisite is not a learning match.
            applied = [k for k in learning if k['keyword'] == '객체지향 프로그래밍']
            related = [k for k in learning if '프로그래밍' in k['keyword']]
            kind, priority = ('application', (2, 0, 0)) if programming_goal and applied else ('exploration', (3, 0 if programming_goal and related else 1, 0))
            selected = applied if kind == 'application' else related or learning
        quote = (selected or evidence or [{}])[0]
        # C is important context for the introductory C course.
        if kind == 'foundation':
            quote = next((k for k in learning if _key(k['keyword']) == 'c'), quote)
        snippet = quote.get('evidence_text') or (re.split(r'(?<=[.!?。])\s+', description.strip())[0] if description else course['course_name'])
        labels = {'direct': '직접 학습', 'foundation': '관련 기초', 'application': '응용·심화', 'exploration': '추가 탐색 후보'}
        prefix = {'direct': '목표와 일치하는 학습 내용', 'foundation': '목표를 위한 프로그래밍 기초', 'application': '목표와 연결해 살펴볼 응용 내용', 'exploration': '관련성을 추가로 확인할 교육과정 내용'}[kind]
        short_quote = snippet[:120] + ('…' if len(snippet) > 120 else '')
        has_source = bool(description or quote.get('evidence_text'))
        reason = f'{prefix}: {short_quote}' if has_source else '과목명만 제공되어 실제 학습 내용과 목표의 관련성을 확인해야 합니다.'
        item = {**course, 'recommendation_type': kind, 'recommendation_label': labels[kind],
                'course_role': kind if kind in ('foundation', 'application') else None,
                'learning_keywords': list(dict.fromkeys(k['keyword'] for k in selected if k['keyword_role'] == 'learning')),
                'keyword_evidence': evidence, 'course_evidence': snippet,
                'evidence_course_id': quote.get('source_course_id') or course['course_id'],
                'evidence_page_start': quote.get('evidence_page_start') or course.get('description_page_start'),
                'evidence_page_end': quote.get('evidence_page_end') or course.get('description_page_end'),
                'reason': reason, 'personalization_reason': reason, 'related_skills': [], 'evidence_refs': [],
                'recommendation_confidence': 'limited', 'description_basis': 'description' if has_source else 'name_inference',
                'limitations': '교육과정 소개에 근거한 후보입니다.' if has_source else '과목명만 제공됩니다.',
                'availability_status': 'not_verified', 'recommendation_kind': 'opinion',
                'availability_notice': '실제 개설과 수강 가능 여부는 학교에서 확인해 주세요.'}
        ranked.append((priority, course.get('recommended_year') or 99, course['course_name'], str(course['course_id']), item))
    ranked.sort(key=lambda r: r[:4])
    ordered = selected_courses([r[3] for r in ranked], [r[4] for r in ranked], review_status)
    direct_count = sum(c['recommendation_type'] == 'direct' for c in ordered)
    return ordered[:max(5, direct_count)]


def recommend(profile, courses, review_status, call=None, skills=()):
    return rank_courses(profile, courses, review_status, skills)

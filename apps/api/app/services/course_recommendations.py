"""Server-owned course ranking and source-grounded explanations."""
import re
import unicodedata

from services.job_skill_analysis import ALIASES, normalize_skill

RULES_VERSION = 'course-evidence-v2'


def available_courses(courses):
    return {str(c['course_id']): c for c in courses if not c['is_completed'] and not c.get('equivalent_completed')}


def selected_courses(ids, courses, review_status):
    allowed = available_courses(courses)
    result, seen = [], set()
    for course_id in ids:
        if course_id in allowed and course_id not in seen and not set(allowed[course_id].get('verified_equivalent_ids', [])) & seen:
            course = dict(allowed[course_id])
            course.pop('description_text', None)
            course['is_completed'] = False
            course['completion_state'] = 'not_selected_in_reviewed_catalog' if review_status in ('confirmed', 'partial') else 'unconfirmed'
            result.append(course)
            seen.add(course_id)
    return result


def _key(value):
    return normalize_skill(value, 'other')[0].casefold()


def _matches(keyword, text):
    if not keyword or not text:
        return False
    normalized = unicodedata.normalize('NFKC', text).casefold()
    if keyword == '기계학습 알고리즘 적용' and '기계학습' in normalized and '적용' in normalized:
        return True
    entry = ALIASES.get(' '.join(unicodedata.normalize('NFKC', keyword).split()).casefold())
    variants = entry[2] if entry else (keyword,)
    for variant in variants:
        pattern = re.escape(unicodedata.normalize('NFKC', variant).casefold()).replace(r'\ ', r'\s*')
        if re.search(r'(?<![a-z0-9_])' + pattern + r'(?![a-z0-9_])', normalized):
            return True
    # Multiword Korean course topics may be written with particles between terms.
    words = re.findall(r'[가-힣]{2,}', keyword)
    return len(words) >= 2 and all(word in normalized for word in words)


def _supports_learning(item):
    keyword, quote = item['keyword'], item['evidence_text']
    if keyword == '기계학습 알고리즘 적용':
        return '기계학습' in quote and '알고리즘' in quote and ('활용' in quote or '적용' in quote)
    return _matches(keyword, quote)


def _goal_learning_match(keyword, goal):
    if not _matches(keyword, goal):
        return False
    entry = ALIASES.get(' '.join(unicodedata.normalize('NFKC', keyword).split()).casefold())
    variants = entry[2] if entry else (keyword,)
    terms = '|'.join(re.escape(v).replace(r'\ ', r'\s*') for v in sorted(variants, key=len, reverse=True))
    pattern = re.compile(r'(?<![a-z0-9_])(?:' + terms + r')(?![a-z0-9_])', re.I)
    normalized = unicodedata.normalize('NFKC', goal)
    matches = list(pattern.finditer(normalized))
    # A single reference describing existing experience is not a request to learn it.
    if len(matches) == 1 and re.match(r'\s*(?:을|를|의)?\s*경험(?:이|은|을)?\s*(?:있|보유)', normalized[matches[0].end():]):
        return False
    return True


def rank_courses(profile, courses, review_status, skills=()):
    goal = ' '.join(str(profile.get(k) or '') for k in ('career_goal', 'target_role'))
    job = [s['skill_name'] for s in skills if s.get('job_requirement', {}).get('recommendation_eligible', True)]
    ranked = []
    for course in available_courses(courses).values():
        description = course.get('description_text') or ''
        evidence = [k for k in course.get('keywords', []) if k.get('evidence_text') and k['evidence_text'] in description]
        learning = [k for k in evidence if k['keyword_role'] == 'learning' and _supports_learning(k)]
        direct_goal = [k for k in learning if _goal_learning_match(k['keyword'], goal)]
        direct_job = [k for k in learning if any(_key(k['keyword']) == _key(name) for name in job)]
        matching = direct_goal or direct_job
        foundation = any(_matches(k['keyword'], '프로그래밍 기초') for k in learning) and bool(re.search(r'프로그래밍|개발|python|javascript|pandas|코딩', goal, re.I))
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
            programming_goal = bool(re.search(r'프로그래밍|개발|python|javascript|pandas|코딩', goal, re.I))
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
        reason = f'{prefix}: {short_quote}' if description else '과목명만 제공되어 실제 학습 내용과 목표의 관련성을 확인해야 합니다.'
        item = {**course, 'recommendation_type': kind, 'recommendation_label': labels[kind],
                'learning_keywords': list(dict.fromkeys(k['keyword'] for k in selected if k['keyword_role'] == 'learning')),
                'keyword_evidence': evidence, 'course_evidence': snippet,
                'evidence_page_start': quote.get('evidence_page_start') or course.get('description_page_start'),
                'evidence_page_end': quote.get('evidence_page_end') or course.get('description_page_end'),
                'reason': reason, 'personalization_reason': reason, 'related_skills': [], 'evidence_refs': [],
                'recommendation_confidence': 'limited', 'description_basis': 'description' if description else 'name_inference',
                'limitations': '교육과정 소개에 근거한 후보입니다.' if description else '과목명만 제공됩니다.',
                'availability_notice': '실제 개설과 수강 가능 여부는 학교에서 확인해 주세요.'}
        ranked.append((priority, course.get('recommended_year') or 99, course['course_name'], str(course['course_id']), item))
    ranked.sort(key=lambda r: r[:4])
    ordered = selected_courses([r[3] for r in ranked], [r[4] for r in ranked], review_status)
    direct_count = sum(c['recommendation_type'] == 'direct' for c in ordered)
    return ordered[:max(5, direct_count)]


def recommend(profile, courses, review_status, call=None, skills=()):
    return rank_courses(profile, courses, review_status, skills)

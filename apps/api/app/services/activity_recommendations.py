"""Conservative KST eligibility and deterministic, source-grounded recommendations."""
from datetime import datetime, timedelta
import re

from services.project_experience import compare_skill, current_comparison, digest

from services.activity_eligibility import KST, period_status, eligible_target, application_period
from services.activity_identity import group_events, source_links
# Synonyms describe a topic, never a posting's unmentioned tool requirements.
TOPICS = {
    '데이터 분석': ('데이터', 'data', '분석', 'analytics', '통계', '시각화'),
    '마케팅': ('마케팅', 'marketing', '마케터', '광고', '브랜딩', '브랜드', '홍보', 'sns'),
    '인공지능': ('인공지능', 'ai', '머신러닝', '딥러닝', 'machine learning'),
    '소프트웨어 개발': ('소프트웨어', '개발', '프로그래밍', '코딩', '해커톤', '앱', 'software', 'developer', '백엔드', '프론트엔드',
                      '웹 개발', '웹 접근성', 'react', 'javascript', 'typescript', 'html', 'css'),
    '디자인': ('디자인', 'design', 'ux', 'ui', '웹툰', '일러스트', 'figma', '프로토타입', '사용성 테스트', '사용자 인터뷰'),
    '영상': ('영상', '영상제작', '영화', 'video', '사진', '콘텐츠', 'content'),
    '창업': ('창업', '사업', '스타트업', 'startup', 'entrepreneur'),
    '보안': ('보안', 'security', '해킹', 'ctf'),
    '환경': ('환경', '기후', '에너지', 'environment', '지속가능'),
    '건축': ('건축', '건설', 'architecture'),
}
# A domain can be the subject of another occupation's work. For an analyst
# studying the environment, an environmental event alone is not analysis practice.
DOMAINS = {'환경', '건축'}
POSTING_FIELDS = (('title', '제목'), ('category', '분야'), ('description_text', '본문'))

def contains(text, word):
    # ASCII boundaries avoid AI in 'campaign', Java in JavaScript, etc.
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(word.lower()) + r'(?![a-z0-9])', text.lower()))


def capture_profile(db, row):
    comparison = current_comparison(db, row)  # Reads existing analyses only; never invokes Gemini.
    grouped = {}
    for item in comparison['project_analysis']['experiences']:
        answer = item.get('user_answer') or {}
        name = (answer['correction']['skill_name'] if answer.get('status') == 'corrected' else item['skill_name'])
        grouped.setdefault(name, []).append(item)
    confirmed = [name for name, items in grouped.items() if compare_skill(items)[0] == 'confirmed_experience']
    gaps = [item['skill_name'] for item in comparison['comparisons']
            if item['student_status'] == 'no_experience' and item['job_requirement'].get('recommendation_eligible', True)]
    profile = {'career_goal': row['career_goal'], 'target_role': row['target_role'],
               'confirmed_skills': sorted(confirmed), 'gap_skills': sorted(gaps)}
    return profile, digest([profile, comparison['project_analysis']['document_basis']])


def match(profile, item):
    reasons, evidence, score = [], [], 0
    topics_by_field = {field: {topic for topic, words in TOPICS.items()
                              if any(contains(profile.get(field) or '', w) for w in words)}
                       for field in ('career_goal', 'target_role')}
    practice_topics = set.union(*topics_by_field.values()) - DOMAINS
    for field, label, weight in (('career_goal', '진로 목표', 8), ('target_role', '희망 직무', 4)):
        value = profile.get(field) or ''
        for topic, words in TOPICS.items():
            if topic not in topics_by_field[field]:
                continue
            if (field == 'career_goal' and topic in DOMAINS and practice_topics
                    and topic not in topics_by_field['target_role']):
                continue
            # '개발' alone also means developing cultural content; it is not
            # evidence of software. Broad goal vocabulary must not create matches.
            source_words = [w for w in words if w not in {'개발', '사업', '콘텐츠', 'content'}]
            for source_field, source_label in POSTING_FIELDS:
                quote = item.get(source_field) or ''
                source_word = next((w for w in source_words if contains(quote, w)), None)
                if source_word:
                    # Selection, score and displayed explanation share this exact
                    # witness. Never fall back to arbitrary shared goal tokens.
                    score += weight + (2 if source_field == 'title' else 0)
                    reasons.append(f'{label} “{value}”에 맞춰, 공고 {source_label} “{quote}”의 “{source_word}” 표현을 근거로 {topic} 관련 활동을 추천합니다.')
                    evidence.append({'student_field': field, 'student_value': value, 'posting_field': source_field,
                                     'posting_quote': quote, 'matched_term': source_word})
                    break
    if not reasons:
        return None  # Experience alone cannot pad unrelated career recommendations.
    for field, label in (('confirmed_skills', '확인한 프로젝트 경험'), ('gap_skills', '경험이 없다고 확인한 보완 후보')):
        for name in profile.get(field, []):
            source_field = next((f for f, _ in POSTING_FIELDS if contains(item.get(f) or '', name)), None)
            if source_field:
                reasons.append(f'{label} “{name}”도 공고의 “{item[source_field]}”에 명시되어 있어 살펴볼 만합니다. 사용 의무나 숙련도는 판단하지 않았습니다.')
                evidence.append({'student_field': field, 'student_value': name, 'posting_field': source_field,
                                 'posting_quote': item[source_field], 'matched_term': name})
                score += 3
                break
    return {'score': score, 'reasons': reasons, 'evidence': evidence}


def recommend(profile, items, sources, now=None, limit=12):
    now = (now or datetime.now(KST)).astimezone(KST)
    recommendations, seen, candidates = [], set(), []
    for item in sorted(items, key=lambda x: (x.get('source', 'contestkorea'), x.get('original_id') or x['id'])):
        identity = (item.get('source', 'contestkorea'), item.get('original_id', item['id']))
        if identity in seen:
            continue
        seen.add(identity)
        period = application_period(item, now)
        candidates.append({**item, 'source': item.get('source', 'contestkorea'), **period, '_registration': period,
                           'application_closed': item.get('application_closed') or item.get('status') in ('종료', '마감', '연습')})
    # Identity and provenance are resolved before eligibility or relevance can
    # discard a source. Expired precise evidence must still close its date-only peer.
    for group in group_events(candidates):
        if any(i.get('application_closed') or i.get('application_cancelled') or
               i.get('candidate_state') in ('closed', 'cancelled') for i in group):
            continue
        periods = [i['_registration'] for i in group]
        exact = [p for p in periods if p.get('deadline_precision') == 'time']
        period = min(exact or periods, key=lambda p: p.get('closes_at') or '9999')
        if period['status'] not in ('open', 'upcoming'):
            continue
        relevant = []
        for item in group:
            if eligible_target(item.get('target') or ''):
                relevance = match(profile, item)
                if relevance:
                    relevant.append((item, relevance))
        if not relevant:
            continue
        item, relevance = min(relevant, key=lambda pair: (-pair[1]['score'], pair[0]['source'], pair[0]['id']))
        label = item.get('source_label', '콘테스트코리아')
        evidence = [{**e, 'source': item.get('source', 'contestkorea'), 'source_label': label,
                     'source_url': item.get('url'), 'original_id': item.get('original_id', item['id'])}
                    for e in relevance['evidence']]
        links = source_links(group)
        recommendations.append({**{k: v for k, v in item.items() if k != '_registration'}, **period, **relevance,
                                'evidence': evidence, 'reasons': [f'{label}: {r}' for r in relevance['reasons']],
                                'source_links': links, 'source_label': ' · '.join(x['source_label'] for x in links)})
    recommendations.sort(key=lambda item: (-item['score'], item['deadline'] or '9999', item['id']))
    recommendations = recommendations[:limit]
    status = 'error' if all(s['status'] == 'error' for s in sources) else 'partial' if any(s['status'] != 'success' for s in sources) else 'success'
    valid_until = now + timedelta(minutes=5)
    for item in recommendations:
        if item['status'] == 'upcoming' and item.get('opens_at'):
            valid_until = min(valid_until, datetime.fromisoformat(item['opens_at']))
        if item['closes_at']:
            valid_until = min(valid_until, datetime.fromisoformat(item['closes_at']))
    return {'status': status, 'activities': recommendations, 'sources': sources,
            'career_goal': profile['career_goal'], 'target_role': profile.get('target_role'),
            'evaluated_at': now.isoformat(), 'valid_until': valid_until.isoformat(),
            'sample_notice': '콘테스트코리아는 Basic DEMO의 공식 limitsu 옵션으로 분야별 최근 최대 1,000건을 조회해 운영자가 수동 수집할 때마다 누적합니다. 데이콘은 공개 목록의 더보기를 끝까지 확인하며 데이커는 데이콘 홈에 노출된 공개 공고를 수집합니다. 전체 공고를 보장하지 않습니다. 발견한 미마감 공고는 서버에서 원문을 재확인하며, 전체 후보 평가와 중복 통합 후 최대 12개를 추천합니다.'}

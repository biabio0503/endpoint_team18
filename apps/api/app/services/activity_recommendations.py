"""Conservative KST eligibility and deterministic, source-grounded recommendations."""
from datetime import datetime, timedelta
import re

from services.project_experience import compare_skill, current_comparison, digest

from services.activity_eligibility import KST, period_status, eligible_target
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
    recommendations, seen = [], set()
    for item in items:
        if item['id'] in seen:
            continue
        seen.add(item['id'])
        period = period_status(item.get('verified_period') or item['period'], now)  # Recheck cache hits too.
        if item.get('source') in ('dacon', 'daker'):
            try:
                start = datetime.fromisoformat(item['application_start_at']).astimezone(KST)
                end = datetime.fromisoformat(item['application_end_at']).astimezone(KST)
                period = {'status': 'upcoming' if now < start else 'closed' if now > end else 'open',
                          'opens_at': start.isoformat(),
                          'deadline': end.date().isoformat(), 'closes_at': end.isoformat(),
                          'deadline_label': end.strftime('%Y-%m-%d %H:%M (한국 시간)')}
            except (KeyError, TypeError, ValueError):
                continue
        if period['status'] not in ('open', 'upcoming') or not eligible_target(item['target']):
            continue
        relevance = match(profile, item)
        if relevance:
            recommendations.append({**item, **period, **relevance})
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
            'sample_notice': '콘테스트코리아는 Basic DEMO 분야별 최근 등록 10건, 데이콘·데이커는 서버가 마지막으로 수집에 성공한 공개 목록 표본입니다. 전체 공고가 아니며 접수 기간과 참가 자격을 확인한 공고만 추천합니다. 변경 사항은 원문을 확인해 주세요.'}

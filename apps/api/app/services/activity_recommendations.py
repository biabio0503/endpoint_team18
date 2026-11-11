"""Conservative KST eligibility and deterministic, source-grounded recommendations."""
from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from services.project_experience import compare_skill, current_comparison, digest

KST = ZoneInfo('Asia/Seoul')
# Synonyms describe a topic, never a posting's unmentioned tool requirements.
TOPICS = {
    '데이터 분석': ('데이터', 'data', '분석', 'analytics', '통계', '시각화'),
    '마케팅': ('마케팅', 'marketing', '마케터', '광고', '브랜딩', '브랜드', '홍보', 'sns'),
    '인공지능': ('인공지능', 'ai', '머신러닝', '딥러닝', 'machine learning'),
    '소프트웨어 개발': ('소프트웨어', '개발', '프로그래밍', '코딩', '해커톤', '앱', 'software', 'developer', '백엔드', '프론트엔드'),
    '디자인': ('디자인', 'design', 'ux', 'ui', '웹툰', '일러스트'),
    '영상': ('영상', '영상제작', '영화', 'video', '사진', '콘텐츠', 'content'),
    '창업': ('창업', '사업', '스타트업', 'startup', 'entrepreneur'),
    '보안': ('보안', 'security', '해킹', 'ctf'),
    '환경': ('환경', '기후', '에너지', 'environment', '지속가능'),
    '건축': ('건축', '건설', 'architecture'),
}
DATE = r'(?:(?P<year>20\d{2})\s*[.\-/년]\s*)?(?P<month>\d{1,2})\s*[.\-/월]\s*(?P<day>\d{1,2})(?:\s*[.일])?'
POINT = re.compile(r'^' + DATE + r'(?:\s*\([월화수목금토일](?:요일)?\))?(?:\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2})|시(?:\s*(?P<kminute>\d{1,2})분)?))?\s*$')
ALWAYS = {'상시', '상시접수', '상시모집', '연중상시', '연중상시접수', '연중접수'}


def period_status(value, now):
    """Require a year anchor. An omitted end year can roll into the next year."""
    value = value.strip()
    if re.sub(r'\s+', '', value) in ALWAYS:
        return {'status': 'open', 'deadline': None, 'deadline_label': '상시 접수', 'closes_at': None}
    parts = re.split(r'\s*(?:~|～|∼|–|부터)\s*', value)
    if len(parts) != 2:
        return {'status': 'unknown'}
    matches = [POINT.fullmatch(re.sub(r'까지$', '', p).strip()) for p in parts]
    if not all(matches):
        return {'status': 'unknown'}
    a, b = [m.groupdict() for m in matches]
    if not a['year'] and not b['year']:
        return {'status': 'unknown'}
    try:
        am, ad, bm, bd = (int(a['month']), int(a['day']), int(b['month']), int(b['day']))
        ay = int(a['year'] or b['year'])
        by = int(b['year'] or a['year'])
        if not b['year'] and (bm, bd) < (am, ad):
            by += 1
        if not a['year'] and (am, ad) > (bm, bd):
            ay -= 1
        start_date, end_date = date(ay, am, ad), date(by, bm, bd)
        start_time = time(int(a['hour'] or 0), int(a['minute'] or a['kminute'] or 0))
        end_time = time(int(b['hour']), int(b['minute'] or b['kminute'] or 0)) if b['hour'] else time.max
        start, end = datetime.combine(start_date, start_time, KST), datetime.combine(end_date, end_time, KST)
        if end < start:
            raise ValueError
    except ValueError:
        return {'status': 'unknown'}
    return {'status': 'upcoming' if now < start else 'closed' if now > end else 'open',
            'deadline': end_date.isoformat(), 'closes_at': end.isoformat(),
            'deadline_label': end_date.isoformat() + (f' {end_time:%H:%M} (한국 시간)' if b['hour'] else ' (한국 시간, 당일 포함)')}


def eligible_target(value):
    # Lists with additional conditions (e.g. 해당자, 지역/학년 제한, 제외) are ambiguous.
    tokens = [t.strip() for t in re.split(r'[,/·ㆍ•|\n]', value) if t.strip()]
    known = {'누구나', '대학생', '대학원생', '일반인', '외국인', '유치원', '초등학생', '중학생', '고등학생'}
    return bool(set(tokens) & {'대학생', '누구나'}) and all(t in known for t in tokens)


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
    for field, label, weight in (('career_goal', '진로 목표', 8), ('target_role', '희망 직무', 4)):
        value = profile.get(field) or ''
        matches = []
        for topic, words in TOPICS.items():
            student_word = next((w for w in words if contains(value, w)), None)
            if not student_word:
                continue
            # '개발' alone also means developing cultural content; it is not
            # evidence of software. Broad goal vocabulary must not create matches.
            source_words = [w for w in words if w not in {'개발', '사업', '콘텐츠', 'content'}]
            for source_field, source_label in (('title', '제목'), ('category', '분야')):
                source_word = next((w for w in source_words if contains(item[source_field], w)), None)
                if source_word:
                    matches.append((topic, source_field, source_label, source_word))
                    score += weight + (2 if source_field == 'title' else 0)
                    break
        # Allow specific goals outside the curated topic vocabulary, without generic fill.
        if not matches:
            stop = {'진로', '목표', '희망', '지망', '취업', '전문가', '대학생', '활동', '공모전', '분야', '기획', '하고', '싶어요', '개발', '사업', '콘텐츠'}
            for word in re.findall(r'[가-힣A-Za-z][가-힣A-Za-z0-9+#]{1,30}', value):
                if word in stop:
                    continue
                for source_field, source_label in (('title', '제목'), ('category', '분야')):
                    if contains(item[source_field], word):
                        matches.append((word, source_field, source_label, word)); score += weight
                        break
        if matches:
            topic, source_field, source_label, word = matches[0]
            quote = item[source_field]
            reasons.append(f'{label} “{value}”에 맞춰, 공고 {source_label} “{quote}”의 “{word}” 표현을 근거로 {topic} 관련 활동을 추천합니다.')
            evidence.append({'student_field': field, 'student_value': value, 'posting_field': source_field,
                             'posting_quote': quote, 'matched_term': word})
    if not reasons:
        return None  # Experience alone cannot pad unrelated career recommendations.
    for field, label in (('confirmed_skills', '확인한 프로젝트 경험'), ('gap_skills', '경험이 없다고 확인한 보완 후보')):
        for name in profile.get(field, []):
            source_field = next((f for f in ('title', 'category') if contains(item[f], name)), None)
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
        if period['status'] != 'open' or not eligible_target(item['target']):
            continue
        relevance = match(profile, item)
        if relevance:
            recommendations.append({**item, **period, **relevance})
    recommendations.sort(key=lambda item: (-item['score'], item['deadline'] or '9999', item['id']))
    recommendations = recommendations[:limit]
    status = 'error' if all(s['status'] == 'error' for s in sources) else 'partial' if any(s['status'] != 'success' for s in sources) else 'success'
    valid_until = now + timedelta(minutes=5)
    for item in recommendations:
        if item['closes_at']:
            valid_until = min(valid_until, datetime.fromisoformat(item['closes_at']))
    return {'status': status, 'activities': recommendations, 'sources': sources,
            'career_goal': profile['career_goal'], 'target_role': profile.get('target_role'),
            'evaluated_at': now.isoformat(), 'valid_until': valid_until.isoformat(),
            'sample_notice': '콘테스트코리아 Basic DEMO의 분야별 최근 등록 10건 표본입니다. 전체 공고가 아니며, 상세 참가 조건과 변경 사항은 원문에서 확인해 주세요.'}

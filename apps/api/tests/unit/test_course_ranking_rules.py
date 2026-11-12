from services.course_recommendations import rank_courses
import json
from pathlib import Path


def course(cid, entries=(), completed=False):
    text = ' '.join(e for _, _, e in entries)
    return {'course_id': cid, 'course_name': cid, 'is_completed': completed,
            'description_text': text, 'keywords': [dict(keyword=k, keyword_role=r, evidence_text=e, evidence_page_start=52) for k, r, e in entries]}


def select(goal, rows, skills=()):
    return rank_courses({'career_goal': goal}, rows, 'confirmed', skills)


def test_minimum_and_all_direct():
    for count in (0, 4, 5, 6):
        result = select('JavaScript 배우고 싶다', [course(str(i), [('JavaScript', 'learning', 'Java script를 배운다.')]) for i in range(count)])
        assert len(result) == count
        assert all(c['recommendation_type'] == 'direct' for c in result)
    rows = [course('direct' + str(i), [('SQL', 'learning', 'SQL을 배운다.')]) for i in range(3)]
    rows += [course('other' + str(i)) for i in range(4)]
    result = select('SQL 학습', rows)
    assert len(result) == 5
    assert [c['recommendation_type'] for c in result[:3]] == ['direct'] * 3
    assert all(c['recommendation_type'] != 'direct' for c in result[3:])


def test_roles_priority_aliases_and_boundaries():
    web = course('웹프로그래밍', [('JavaScript', 'learning', 'Java script 원리를 배운다.')])
    basic = course('프로그래밍입문(1)', [('프로그래밍 기초', 'learning', '프로그래밍 기초를 배운다.'), ('C', 'learning', 'C언어를 배운다.')])
    data = course('데이터분석', [('Python', 'prerequisite', 'Python 사전지식이 필요하다.'), ('기계학습 알고리즘 적용', 'learning', '기계학습 알고리즘을 데이터 분석에 적용한다.')])
    pandas = course('오픈소스소프트웨어', [('pandas', 'example', 'pandas는 예시 프로젝트다.')])
    java = course('Java', [('Java', 'learning', 'Java를 배운다.')])
    rows = [basic, data, pandas, java, web]
    js = select('JavaScript 경험 없음', rows)
    assert js[0]['course_id'] == '웹프로그래밍' and js[0]['course_evidence'] == 'Java script 원리를 배운다.'
    assert next(c for c in js if c['course_id'] == 'Java')['recommendation_type'] != 'direct'
    py = select('Python 경험 없음과 프로그래밍 입문', rows)
    assert next(c for c in py if c['course_id'] == '데이터분석')['recommendation_type'] != 'direct'
    assert 'C언어' in next(c for c in py if c['course_id'] == '프로그래밍입문(1)')['personalization_reason']
    pd = select('pandas 학습', rows)
    assert next(c for c in pd if c['course_id'] == '오픈소스소프트웨어')['recommendation_type'] != 'direct'
    ml = select('Python 경험이 있고 기계학습을 데이터 분석에 적용하고 싶다', rows)
    assert ml[0]['course_id'] == '데이터분석'
    assert {k['keyword_role'] for k in ml[0]['keyword_evidence']} == {'learning', 'prerequisite'}
    python = course('파이썬 입문', [('Python', 'learning', 'Python 문법을 배운다.')])
    ml = select('Python 경험이 있고 기계학습을 데이터 분석에 적용하고 싶다', [python, data])
    assert ml[0]['course_id'] == '데이터분석'
    assert next(c for c in ml if c['course_id'] == '파이썬 입문')['recommendation_type'] != 'direct'


def test_verified_equivalence_and_invalid_evidence():
    a = course('a', [('SQL', 'learning', 'SQL을 배운다.')]); a['verified_equivalent_ids'] = ['b']
    b = course('b', [('SQL', 'learning', 'SQL을 배운다.')]); b['verified_equivalent_ids'] = ['a']
    excluded = course('excluded', [('SQL', 'learning', 'SQL을 배운다.')], True)
    fake = course('fake', [('SQL', 'learning', '다른 문서의 문장')]); fake['description_text'] = 'DBMS 소개'
    unsupported = course('unsupported', [('SQL', 'learning', 'DBMS를 학습한다.')])
    result = select('SQL 배우기', [a, b, excluded, fake, unsupported])
    assert [c['course_id'] for c in result] == ['a', 'unsupported', 'fake']
    assert result[1]['recommendation_type'] == 'direct'  # reviewed mapping and exact source quote
    assert result[2]['recommendation_type'] != 'direct'


def test_technology_boundaries_aliases_and_korean_particles():
    rows = [course(name, [(name, 'learning', '공식 강의 소개.')])
            for name in ('C', 'C++', 'C#', 'Java', 'JavaScript', 'CNN')]
    def direct(goal):
        return {c['course_id'] for c in select(goal, rows) if c['recommendation_type'] == 'direct'}
    assert direct('C++를 배우고 싶다') == {'C++'}
    assert direct('C와 C++를 둘 다 배우고 싶다') == {'C', 'C++'}
    assert direct('C#을 배우고 싶다.') == {'C#'}
    assert direct('JavaScript를 배우기') == {'JavaScript'}
    assert direct('Java, C를 배우기') == {'Java', 'C'}
    assert direct('convolutional neural network를 배우기') == direct('CNN을 배우기') == {'CNN'}


def test_aliases_apply_to_the_whole_order_and_all_direct_are_first():
    rows = [course('basic', [('프로그래밍 기초', 'learning', '기초 학습.'), ('C', 'learning', 'C언어 학습.')]),
            course('application', [('객체지향 프로그래밍', 'learning', '객체지향 학습.')]),
            *[course(str(i), [('Python', 'learning', '파이썬 학습.')]) for i in range(6)]]
    english, korean = select('Python 입문', rows), select('파이썬 입문', rows)
    assert [(c['course_id'], c['recommendation_type']) for c in english] == [(c['course_id'], c['recommendation_type']) for c in korean]
    assert len(english) == 6 and all(c['recommendation_type'] == 'direct' for c in english)
    assert all(c['availability_status'] == 'not_verified' for c in english)


def test_unreviewed_roles_and_wrong_course_quotes_are_not_direct():
    rows = [course(role, [('CNN', role, '합성곱 신경망을 다룬다.')])
            for role in ('prerequisite', 'tool', 'example', 'context')]
    wrong = course('wrong', [('CNN', 'learning', '다른 과목의 문장.')])
    wrong['description_text'] = '이 과목의 소개.'
    rows.append(wrong)
    assert all(c['recommendation_type'] != 'direct' for c in select('CNN 학습', rows))


def test_bilingual_member_evidence_stays_with_its_own_description():
    from course_groups import GROUPS_BY_CATALOG, grouped_courses
    group = GROUPS_BY_CATALOG['seoultech-cse-2026-major-v1'][0]
    korean, english = (m['course_id'] for m in group['members'])
    rows = [course(korean, []), course(english, [('CNN', 'learning', 'Convolutional networks are covered.')])]
    grouped = grouped_courses(rows, 'seoultech-cse-2026-major-v1')
    result = select('CNN', grouped)[0]
    assert result['recommendation_type'] == 'direct'
    assert result['evidence_course_id'] == english
    assert '_keyword_sources' not in result
    grouped[0]['_keyword_sources'][1]['description_text'] = 'Unrelated description.'
    assert select('CNN', grouped)[0]['recommendation_type'] != 'direct'
    grouped[0]['_keyword_sources'].append({'course_id': 'foreign', 'description_text': 'foreign quote',
        'keywords': [{'keyword': 'CNN', 'keyword_role': 'learning', 'evidence_text': 'foreign quote'}]})
    assert select('CNN', grouped)[0]['recommendation_type'] != 'direct'


def test_explicit_goal_ranks_before_job_evidence_and_job_experience():
    web = course('web', [('JavaScript', 'learning', 'Java script를 배운다.')])
    python = course('python', [('Python', 'learning', 'Python을 배운다.')])
    sql = course('sql', [('SQL', 'learning', 'SQL을 배운다.')])
    skills = [{'skill_name': 'Python', 'student_status': 'confirmed_experience', 'job_requirement': {}},
              {'skill_name': 'SQL', 'student_status': 'no_experience', 'job_requirement': {}}]
    result = select('JavaScript를 배우고 싶다', [python, sql, web], skills)
    assert [c['course_id'] for c in result] == ['web', 'sql', 'python']


def test_goal_alias_spans_and_prior_learning():
    rows = [course(name, [(name, 'learning', '공식 강의 소개.')])
            for name in ('C', 'C++', 'C#', 'Java', 'JavaScript')]
    def direct(goal):
        return {c['course_id'] for c in select(goal, rows) if c['recommendation_type'] == 'direct'}
    for goal in ('C++ 입문', 'C plus plus 입문'):
        assert direct(goal) == {'C++'}
    for goal in ('C# 입문', 'C sharp 입문'):
        assert direct(goal) == {'C#'}
    for goal in ('JavaScript 입문', 'Java script 입문', '자바스크립트 입문'):
        assert direct(goal) == {'JavaScript'}
    assert direct('Java와 JavaScript를 배우고 싶다') == {'Java', 'JavaScript'}
    assert direct('C는 이미 배웠고 C++를 배우고 싶다') == {'C++'}
    assert direct('C++는 이미 배웠고 C를 배우고 싶다') == {'C'}
    assert direct('C와 C++를 배우고 싶다') == {'C', 'C++'}
    assert direct('C를 이미 배웠고 C를 다시 배우고 싶다') == {'C'}
    assert direct('C 경험 없음') == {'C'}


def test_job_evidence_does_not_turn_explicitly_past_skill_into_learning_goal():
    rows = [course(name, [(name, 'learning', '공식 강의 소개.')]) for name in ('C', 'C++')]
    skills = [{'skill_name': 'C', 'student_status': 'confirmed_experience', 'job_requirement': {}},
              {'skill_name': 'C++', 'student_status': 'no_experience', 'job_requirement': {}}]
    result = select('C는 이미 배웠고 C++를 배우고 싶다', rows, skills)
    assert [(c['course_id'], c['recommendation_type']) for c in result] == [('C++', 'direct'), ('C', 'exploration')]


def test_shared_predicates_catalog_terms_and_per_keyword_evidence():
    rows = [course(name, [(name, 'learning', '공식 강의 소개.')])
            for name in ('C', 'C++', 'JavaScript', '자료구조', 'CNN')]
    rows.append(course('mixed', [('자료구조', 'learning', '자료구조를 가르친다.'),
                                 ('CNN', 'learning', 'CNN을 가르친다.')]))
    skills = [{'skill_name': name, 'student_status': 'confirmed_experience', 'job_requirement': {}}
              for name in ('C', 'C++', '자료구조')]
    def direct(goal, jobs=()):
        return {c['course_id']: c['learning_keywords'] for c in select(goal, rows, jobs)
                if c['recommendation_type'] == 'direct'}

    for goal in ('C와 C++는 이미 배웠고 JavaScript를 배우고 싶다',
                 'C는 이미 배웠고 C++도 이미 배웠고 JavaScript를 배우고 싶다'):
        assert direct(goal, skills[:2]) == {'JavaScript': ['JavaScript']}
    assert direct('자료구조는 이미 배웠고 CNN을 배우고 싶다', skills[2:]) == {'CNN': ['CNN'], 'mixed': ['CNN']}
    assert direct('자료구조와 CNN을 함께 배우고 싶다') == {
        '자료구조': ['자료구조'], 'CNN': ['CNN'], 'mixed': ['자료구조', 'CNN']}
    assert direct('자료구조와 CNN을 이미 배웠고 자료구조를 다시 배우고 싶다') == {
        '자료구조': ['자료구조'], 'mixed': ['자료구조']}
    assert '자료구조' in direct('자료구조 경험 없음과 CNN 학습')


def test_compound_mentions_do_not_cross_clauses_and_keep_their_own_predicate():
    rows = [course('compound', [('기계학습 알고리즘 적용', 'learning', '공식 소개.')]),
            course('cnn', [('CNN', 'learning', '공식 소개.')]),
            course('other', [('데이터 구조 분석', 'learning', '공식 소개.')])]
    def direct(goal, skills=()):
        return {c['course_id']: c['learning_keywords'] for c in select(goal, rows, skills)
                if c['recommendation_type'] == 'direct'}

    assert direct('기계학습을 이미 배웠고 CNN을 영상에 적용하고 싶다') == direct('CNN을 영상에 적용하고 싶다') == {'cnn': ['CNN']}
    past = '기계학습 알고리즘 적용은 이미 배웠고 CNN을 배우고 싶다'
    particles = '기계학습 알고리즘의 적용은 이미 배웠고 CNN을 배우고 싶다'
    assert direct(past) == direct(particles) == {'cnn': ['CNN']}
    assert direct(particles, [{'skill_name': '기계학습 알고리즘 적용', 'job_requirement': {}}]) == {'cnn': ['CNN']}
    assert direct('기계학습 알고리즘을 적용하는 방법을 배우고 싶다') == {'compound': ['기계학습 알고리즘 적용']}
    assert direct('기계학습 알고리즘을 CNN에 적용하는 방법을 배우고 싶다') == {
        'compound': ['기계학습 알고리즘 적용'], 'cnn': ['CNN']}
    assert direct('기계학습을 이미 배웠고 기계학습 알고리즘을 적용하는 방법을 배우고 싶다') == {'compound': ['기계학습 알고리즘 적용']}
    assert direct('데이터 구조의 분석은 이미 배웠고 CNN을 배우고 싶다') == {'cnn': ['CNN']}
    assert direct('데이터를 이미 배웠고 CNN을 분석하고 싶다') == {'cnn': ['CNN']}
    assert direct('데이터 구조를 분석하는 방법을 배우고 싶다') == {'other': ['데이터 구조 분석']}


def test_compounds_require_their_components_or_a_reviewed_equivalent():
    rows = [course('vision', [('디지털 영상 해석', 'learning', '공식 소개.')]),
            course('database', [('데이터 중복 관리', 'learning', '공식 소개.')]),
            course('ml', [('기계학습 알고리즘 적용', 'learning', '공식 소개.')])]
    def direct(goal):
        return {c['course_id']: c['learning_keywords'] for c in select(goal, rows)
                if c['recommendation_type'] == 'direct'}

    assert direct('디지털 영상 해석') == {'vision': ['디지털 영상 해석']}
    assert direct('디지털 영상을 해석하는 방법') == {'vision': ['디지털 영상 해석']}
    assert direct('디지털 회로 해석') == {}
    assert direct('데이터 중복 관리') == {'database': ['데이터 중복 관리']}
    assert direct('데이터 중복을 관리하는 방법') == {'database': ['데이터 중복 관리']}
    assert direct('데이터 품질 관리') == {}
    assert direct('기계학습을 데이터 분석에 적용하고 싶다') == {'ml': ['기계학습 알고리즘 적용']}
    assert direct('기계학습을 영상에 적용하고 싶다') == {}
    assert direct('기계학습의 데이터 분석 적용은 이미 배웠다') == {}


def test_catalog_compounds_do_not_match_replaced_middle_components():
    from services.course_recommendations import _matches
    path = Path(__file__).resolve().parents[1] / 'fixtures/seoultech_cse_2026_course_evidence.json'
    snapshot = json.loads(path.read_text())
    keywords = {k['keyword'] for c in snapshot for k in c['keywords']
                if k['keyword_role'] == 'learning' and len(k['keyword'].split()) >= 3}
    assert keywords
    middle_words = {word for keyword in keywords for word in keyword.split()[1:-1]}
    for keyword in keywords:
        words = keyword.split()
        assert _matches(keyword, keyword), keyword
        for replacement in middle_words | {'무관'}:
            if replacement in words[1] or words[1] in replacement:
                continue
            changed = ' '.join([words[0], replacement, *words[2:]])
            assert not _matches(keyword, changed), (keyword, changed)

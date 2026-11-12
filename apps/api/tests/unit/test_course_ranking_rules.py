from services.course_recommendations import rank_courses


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
    assert [c['course_id'] for c in result] == ['a', 'fake', 'unsupported']
    assert result[1]['recommendation_type'] != 'direct'
    assert result[2]['recommendation_type'] != 'direct'


def test_explicit_goal_ranks_before_job_evidence_and_job_experience():
    web = course('web', [('JavaScript', 'learning', 'Java script를 배운다.')])
    python = course('python', [('Python', 'learning', 'Python을 배운다.')])
    sql = course('sql', [('SQL', 'learning', 'SQL을 배운다.')])
    skills = [{'skill_name': 'Python', 'student_status': 'confirmed_experience', 'job_requirement': {}},
              {'skill_name': 'SQL', 'student_status': 'no_experience', 'job_requirement': {}}]
    result = select('JavaScript를 배우고 싶다', [python, sql, web], skills)
    assert [c['course_id'] for c in result] == ['web', 'sql', 'python']

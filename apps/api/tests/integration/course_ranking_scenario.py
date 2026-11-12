from contextlib import closing
from unittest.mock import patch
from roadmap_scenario import RoadmapAPI, C, U, DB_COURSE, fake_roadmap
from repositories.plans import connect
from repositories.courses import CourseRepository
from api.domain import now

case = RoadmapAPI('test_roadmap_persistence_cache_progress_refresh')
case.setUp()
try:
    with closing(connect()) as db:
        for i in range(6):
            cid = 'sql-ranking-' + str(i)
            sentence = 'SQL 데이터 조회 방법을 학습한다.'
            db.execute('INSERT INTO courses(course_id,university_id,canonical_name) VALUES(?,?,?)', (cid, U, cid))
            db.execute('INSERT INTO catalog_courses(catalog_id,course_id,course_name,description_text) VALUES(?,?,?,?)', (C, cid, cid, sentence))
            db.execute('INSERT INTO catalog_course_keywords(catalog_id,course_id,keyword,keyword_role,evidence_text,evidence_page_start) VALUES(?,?,?,?,?,?)', (C, cid, 'SQL', 'learning', sentence, 12))
        db.commit()
    response = case.client.patch(case.base, json={'expected_input_revision': case.revision(), 'changes': {'career_goal': 'SQL 학습 희망'}})
    assert response.status_code == 200, response.text
    basic = case.client.post(case.base + '/course-recommendations', json={})
    assert basic.status_code == 200, basic.text
    chosen = basic.json()['courses']
    assert len(chosen) == 6 and all(c['recommendation_type'] == 'direct' for c in chosen)
    no_jobs = case.make()
    assert no_jobs.status_code == 201, no_jobs.text
    assert [c['course_id'] for c in no_jobs.json()['recommended_courses']] == [c['course_id'] for c in chosen]
    assert no_jobs.json()['generation_mode'] == 'limited_guidance'
    old = no_jobs.json()['run_id']
    case.jobs()
    def short_provider(data):
        result = fake_roadmap(data)
        skill = next(s for s in data['skills'] if s['skill_name'] == 'SQL')
        courses = [{'course_id': c['course_id'], 'related_skills':['SQL'], 'evidence_refs':[skill['comparison_ref']],
                    'course_evidence':'모델이 잘못 쓴 문장', 'reason':'SQL을 가르친다고 잘못 쓴 설명',
                    'personalization_reason':'모델 설명', 'course_role':'foundation', 'recommendation_confidence':'supported'}
                   for c in reversed(data['eligible_courses'][:3])]
        return result.model_copy(update={'recommended_courses': courses})
    with patch('api.routes.roadmaps.generate_roadmap', side_effect=short_provider):
        generated = case.make()
    assert generated.status_code == 201, generated.text
    result = generated.json()
    assert [c['course_id'] for c in result['recommended_courses']] == [c['course_id'] for c in chosen]
    assert all('모델' not in c['personalization_reason'] for c in result['recommended_courses'])
    assert case.client.get(case.base + '/roadmaps/' + old).status_code == 200
    # A prior roadmap basis stays readable but cannot satisfy a new request.
    changed = case.client.patch(case.base, json={'expected_input_revision': case.revision(),
                                'changes': {'career_goal': 'SQL 학습 희망과 심화'}})
    assert changed.status_code == 200, changed.text
    with patch('services.roadmap_generation.RULES_VERSION', 'personalized-roadmap-v7-normalized-course-goals'), \
         patch('api.routes.roadmaps.generate_roadmap', side_effect=short_provider):
        previous = case.make()
    assert previous.status_code == 201, previous.text
    previous_id = previous.json()['run_id']
    assert case.client.get(case.base + '/roadmaps/' + previous_id).json()['run_id'] == previous_id
    with patch('api.routes.roadmaps.generate_roadmap', side_effect=short_provider):
        upgraded = case.make()
    assert upgraded.status_code == 201 and upgraded.json()['run_id'] != previous_id, upgraded.text
    restored = case.client.get(case.base + '/roadmaps/' + previous_id)
    assert restored.status_code == 200 and restored.json()['run_id'] == previous_id
    # Simulate a cache entry under an earlier rule, then require a new-rule response.
    with patch('api.routes.recommendations.RULES_VERSION', 'old-course-rules'), \
         patch('api.routes.recommendations.recommend', return_value=chosen[:3]):
        legacy = case.client.post(case.base + '/course-recommendations', json={})
    assert len(legacy.json()['courses']) == 3
    from services.course_recommendations import recommend
    with patch('api.routes.recommendations.recommend', wraps=recommend) as current_recommend:
        current = case.client.post(case.base + '/course-recommendations', json={})
        assert current_recommend.call_count == 2  # cache miss plus post-read verification
        repeated = case.client.post(case.base + '/course-recommendations', json={})
        assert current_recommend.call_count == 3  # cached plus post-read verification
    assert len(current.json()['courses']) == len(repeated.json()['courses']) == 6
    # Exercise actual HTTP responses after changing completion state, including 0.
    for remaining in (5, 4, 0):
        with closing(connect()) as db:
            repo = CourseRepository(db)
            repo.save_state(case.rid, DB_COURSE, C, True, now())
            for i in range(6):
                repo.save_state(case.rid, 'sql-ranking-' + str(i), C, i >= remaining, now())
            repo.changed(case.rid, now())
            db.commit()
        response = case.client.post(case.base + '/course-recommendations', json={})
        assert response.status_code == 200, response.text
        assert len(response.json()['courses']) == remaining
        assert bool(response.json()['reason']) == (remaining < 5)
finally:
    case.tearDown()

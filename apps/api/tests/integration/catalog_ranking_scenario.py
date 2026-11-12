"""Exercise both POST APIs with a read-only snapshot of the CSE catalog; no live AI."""
from contextlib import closing
import json
from pathlib import Path

from roadmap_scenario import RoadmapAPI, U, D
from repositories.plans import connect

CATALOG = 'seoultech-cse-2026-major-v1'
snapshot = json.loads((Path(__file__).parents[1] / 'fixtures/seoultech_cse_2026_course_evidence.json').read_text())
from course_groups import grouped_courses

grouped = grouped_courses(snapshot, CATALOG)
reviewed = [(source, k) for course in grouped for source in (course.get('_keyword_sources') or [course])
            for k in source['keywords'] if k['keyword_role'] == 'learning']
assert len(reviewed) == 291
assert all(k['evidence_text'].strip() and k['evidence_text'] in (source['description_text'] or '') for source, k in reviewed)
case = RoadmapAPI('test_roadmap_persistence_cache_progress_refresh')
case.setUp()
try:
    with closing(connect()) as db:
        db.execute('''INSERT INTO course_catalogs(catalog_id,department_id,version_label,scope_description,
            completeness_status,source_name,retrieved_at,is_selectable) VALUES(?,?,?,?,?,?,?,TRUE)''',
            (CATALOG, D, 'snapshot', 'read-only CSE catalog snapshot', 'complete', 'test snapshot', '2026-11-12T00:00:00+00:00'))
        for c in snapshot:
            db.execute('INSERT INTO courses(course_id,university_id,canonical_name) VALUES(?,?,?)', (c['course_id'], U, c['course_name']))
            db.execute('''INSERT INTO catalog_courses(catalog_id,course_id,course_name,course_code,credits,category,
                recommended_year,recommended_term,description_text,description_page_start,description_page_end)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (CATALOG, c['course_id'], c['course_name'], c['course_code'], c['credits'],
                    c['category'], c['recommended_year'], c['recommended_term'], c['description_text'],
                    c['description_page_start'], c['description_page_end']))
            for k in c['keywords']:
                db.execute('''INSERT INTO catalog_course_keywords(catalog_id,course_id,keyword,keyword_role,evidence_text,
                    evidence_page_start,evidence_page_end) VALUES(?,?,?,?,?,?,?)''',
                    (CATALOG, c['course_id'], k['keyword'], k['keyword_role'], k['evidence_text'],
                     k['evidence_page_start'], k['evidence_page_end']))
        db.commit()
    response = case.client.patch(case.base, json={'expected_input_revision': case.revision(), 'changes': {'catalog_id': CATALOG}})
    assert response.status_code == 200, response.text
    results = {}
    for goal in ('Python 입문', '파이썬 입문', 'C++ 입문', 'C와 C++', 'CNN',
                 'convolutional neural network', 'JavaScript 입문', 'pandas 학습',
                 'C plus plus 입문', 'C# 입문', 'C sharp 입문', 'Java script 입문', '자바스크립트 입문',
                 'Java와 JavaScript를 배우고 싶다', 'C는 이미 배웠고 C++를 배우고 싶다',
                 'C++는 이미 배웠고 C를 배우고 싶다', 'C와 C++를 배우고 싶다'):
        response = case.client.patch(case.base, json={'expected_input_revision': case.revision(),
                                                     'changes': {'career_goal': goal, 'target_role': None}})
        assert response.status_code == 200, response.text
        course_response = case.client.post(case.base + '/course-recommendations', json={})
        assert course_response.status_code == 200, course_response.text
        roadmap_response = case.make()
        assert roadmap_response.status_code == 201, roadmap_response.text
        assert roadmap_response.json()['generation_mode'] == 'limited_guidance'
        courses = course_response.json()['courses']
        roadmap_courses = roadmap_response.json()['recommended_courses']
        signature = lambda rows: [(c['course_id'], c['recommendation_type']) for c in rows]
        assert signature(courses) == signature(roadmap_courses)
        assert all(c['availability_status'] == 'not_verified' for c in courses + roadmap_courses)
        results[goal] = courses
    assert signature(results['Python 입문']) == signature(results['파이썬 입문'])
    assert signature(results['CNN']) == signature(results['convolutional neural network'])
    assert signature(results['C++ 입문']) == signature(results['C plus plus 입문'])
    assert signature(results['C# 입문']) == signature(results['C sharp 입문'])
    assert signature(results['JavaScript 입문']) == signature(results['Java script 입문']) == signature(results['자바스크립트 입문'])
    assert all(c['recommendation_type'] != 'direct' for c in results['C# 입문'])
    assert results['C는 이미 배웠고 C++를 배우고 싶다'][0]['course_name'].startswith('프로그래밍입문(2)')
    assert results['C++는 이미 배웠고 C를 배우고 싶다'][0]['course_name'].startswith('프로그래밍입문(1)')
    assert all(c['recommendation_type'] == 'direct' for c in results['C와 C++를 배우고 싶다'][:2])
    assert results['Java와 JavaScript를 배우고 싶다'][0]['recommendation_type'] == 'direct'
    assert results['C++ 입문'][0]['course_name'].startswith('프로그래밍입문(2)')
    assert results['C++ 입문'][0]['recommendation_type'] == 'direct'
    assert next(c for c in results['C++ 입문'] if c['course_name'].startswith('프로그래밍입문(1)'))['recommendation_type'] == 'foundation'
    assert all(c['recommendation_type'] == 'direct' for c in results['C와 C++'][:2])
    assert {c['course_name'].split(' (')[0] for c in results['CNN'][:2]} == {'기계학습', '인공지능개론'}
    assert all(c['recommendation_type'] == 'direct' for c in results['CNN'][:2])
    assert results['JavaScript 입문'][0]['course_name'] == '웹프로그래밍'
    assert results['JavaScript 입문'][0]['recommendation_type'] == 'direct'
    assert all(c['recommendation_type'] != 'direct' for c in results['pandas 학습'])
    for goal, courses in results.items():
        print(f"{goal}: {courses[0]['course_name']} [{courses[0]['recommendation_type']}] ({len(courses)} courses)")
    print(f'Both POST APIs: {len(results)} catalog goals agree; alias signatures match; no live Gemini calls.')
finally:
    case.tearDown()

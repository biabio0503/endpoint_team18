"""Synthetic API scenarios shared by isolated SQLite and PostgreSQL. AI is mocked."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
import uuid
from unittest.mock import patch

from project_experience_scenario import ProjectExperienceAPI, fake_extraction, job_result
from repositories.plans import connect, Repository
from services.gemini import GeminiError
from services.roadmap_schemas import GeneratedRoadmap

U, D, C, C2 = ('roadmap-test-' + s for s in ('university', 'department', 'catalog', 'outside-catalog'))
DB_COURSE, OTHER_COURSE = 'roadmap-test-database', 'roadmap-test-same-name'


def fake_roadmap(data):
    """Contract fixture adapts to actual server input; never used by production code."""
    skill = next(s for s in data['skills'] if s['skill_name'] == 'SQL')
    status = skill['student_status']
    intent = 'deepen' if status == 'confirmed_experience' else 'learn' if status == 'no_experience' else 'verify_experience'
    courses = [c for c in data['eligible_courses'] if c['course_id'] == DB_COURSE]
    selected = [{'course_id': c['course_id'], 'related_skills': ['SQL'], 'evidence_refs': [skill['comparison_ref']],
                 'course_evidence': c['description_text'] or c['course_name'], 'reason': 'SQL 데이터 조회 개념과 관련된 후보',
                 'personalization_reason': status + ' 상태 반영', 'course_role': 'advanced' if intent == 'deepen' else 'foundation',
                 'recommendation_confidence': 'supported'} for c in courses]
    return GeneratedRoadmap(recommended_courses=selected, roadmap=[{
        'step_id': f'step-{i}', 'order': i, 'title': f'{intent} 활동 {i}', 'purpose': 'SQL 활용 준비',
        'reason': status + ' 상태에 따른 추천 의견', 'skill_targets': [{'skill_name': 'SQL', 'student_status': status, 'action_type': intent}],
        'related_course_ids': [c['course_id'] for c in selected], 'depends_on': [f'step-{i-1}'] if i > 1 else [],
        'evidence_refs': [skill['comparison_ref']], 'limitations': '해외 공고 표본과 현재 확인 자료에 한정',
        'tasks': [{'task_id': f'task-{i}', 'task_type': 'verify_experience' if intent == 'verify_experience' else 'apply',
                   'title': f'{intent} 작업 {i}', 'action': f'SQL 경험 확인 자료 {i}를 정리한다.' if intent == 'verify_experience' else f'{intent} 구체 작업 {i}를 수행한다.',
                   'completion_criteria': '검토 가능한 실행 파일과 결과 기록', 'deliverable': f'결과 기록 {i}'}],
    } for i in range(1, 4)])


class RoadmapAPI(ProjectExperienceAPI):
    def test_context_only_evidence_never_calls_paid_roadmap_generation(self):
        result = job_result()
        for skill in result['skills']:
            skill['recommendation_eligible'] = False
            skill['supporting_job_count'] = 0
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=result):
            self.assertEqual(self.client.post(self.base + '/job-skill-analysis', json={}).status_code, 200)
        with patch('api.routes.roadmaps.generate_roadmap') as ai:
            response = self.make()
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['generation_mode'], 'limited_guidance')
            self.assertEqual([c['course_id'] for c in response.json()['recommended_courses']], [DB_COURSE])
            self.assertEqual(response.json()['recommended_courses'][0]['recommendation_type'], 'exploration')
            ai.assert_not_called()

    def test_previous_rules_preserve_reads_evidence_progress_and_explicit_upgrade(self):
        from services import project_experience as experience
        from repositories.experience_analysis import AnalysisRepository
        from repositories.roadmaps import RoadmapRepository
        legacy = job_result()
        legacy.pop('analysis_version')
        legacy.update(career_goal='데이터 분석 분야', target_role='데이터 분석가')
        # Create a genuine old-version basis/cache key and saved run in the isolated DB.
        with patch.object(experience, 'JOB_VERSION', 'job-skills-v1'), \
             patch('services.roadmap_generation.RULES_VERSION', 'personalized-roadmap-v2'), \
             patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=legacy):
            saved = self.client.post(self.base + '/job-skill-analysis', json={}).json()
            old, _ = self.generated()
            response = self.client.patch(f'{self.base}/roadmaps/{old["run_id"]}/tasks/task-1', json={
                'is_completed': True, 'expected_progress_version': 0})
            self.assertEqual(response.status_code, 200, response.text)
        with closing(connect()) as db:
            row = db.execute('SELECT * FROM roadmap_inputs WHERE request_id=?', (self.rid,)).fetchone()
            self.assertIsNone(AnalysisRepository(db).job(self.rid, experience.job_basis(row)))
            original_run = RoadmapRepository(db).get(self.rid, old['run_id'])
            original_snapshot = AnalysisRepository(db).job_history(self.rid)[0]
        with patch('api.routes.job_skill_analysis.analyze_job_skills') as jobs, \
             patch('api.routes.roadmaps.generate_roadmap') as roadmap:
            for _ in range(2):  # Entry and browser reload are read-only.
                comparison = self.comparison()
                self.assertTrue(comparison['job_analysis']['previous_analysis_version'])
                self.assertEqual(comparison['job_analysis']['snapshot_id'], saved['snapshot_id'])
                self.assertEqual(comparison['job_analysis']['skills'], legacy['skills'])
                self.assertEqual(self.client.get(self.base + '/roadmap').json()['run_id'], old['run_id'])
                restored = self.client.get(f'{self.base}/roadmaps/{old["run_id"]}').json()
                self.assertTrue(restored['is_stale'])
                self.assertFalse(restored['details_restricted'])
                self.assertEqual(restored['evidence'], old['evidence'])
                self.assertEqual(restored['progress']['completed'], 1)
                self.assertEqual(self.client.get(self.base + '/roadmaps').status_code, 200)
            # New roadmap cannot silently use obsolete job relevance rules.
            self.assertEqual(self.make(True).json()['error'], 'job_analysis_outdated')
            jobs.assert_not_called(); roadmap.assert_not_called()
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value={'status':'error','errors':[]}) as ai:
            failed = self.client.post(self.base + '/job-skill-analysis', json={'refresh':True}).json()
            self.assertEqual(failed['snapshot_id'], saved['snapshot_id'])
            self.assertIn('refresh_error', failed)
            self.assertEqual(ai.call_count, 1)
        # Explicit POST upgrades to v2 and retains the v1 snapshot/run rows.
        upgraded, calls = self.jobs()
        self.assertEqual(calls, 1)
        self.assertEqual(upgraded['analysis_version'], 'job-skills-v2')
        self.assertNotEqual(upgraded['snapshot_id'], saved['snapshot_id'])
        with closing(connect()) as db:
            self.assertEqual(RoadmapRepository(db).get(self.rid, old['run_id']), original_run)
            self.assertIn(original_snapshot, AnalysisRepository(db).job_history(self.rid))
        new, _ = self.generated()
        self.assertNotEqual(new['run_id'], old['run_id'])
        self.assertEqual(new['rules_version'], 'personalized-roadmap-v9-keyword-experience')
        self.assertEqual(new['progress']['completed'], 0)
        self.assertEqual(self.client.get(f'{self.base}/roadmaps/{old["run_id"]}').json()['progress']['completed'], 1)

    def setUp(self):
        super().setUp()
        with closing(connect()) as db:
            db.execute('INSERT INTO universities VALUES(?,?,TRUE) ON CONFLICT DO NOTHING', (U, 'Synthetic'))
            db.execute('INSERT INTO departments VALUES(?,?,?,TRUE) ON CONFLICT DO NOTHING', (D, U, 'Synthetic'))
            for cid in (C, C2):
                db.execute('''INSERT INTO course_catalogs(catalog_id,department_id,version_label,scope_description,
                    completeness_status,source_name,retrieved_at,is_selectable) VALUES(?,?,?,?,?,?,?,TRUE) ON CONFLICT DO NOTHING''',
                    (cid, D, 'test', 'synthetic catalog', 'complete', 'test', '2026-11-09T00:00:00+00:00'))
            for course, cid in ((DB_COURSE, C), (OTHER_COURSE, C2)):
                db.execute('INSERT INTO courses(course_id,university_id,canonical_name) VALUES(?,?,?) ON CONFLICT DO NOTHING', (course, U, '데이터베이스'))
                db.execute('INSERT INTO catalog_courses(catalog_id,course_id,course_name,course_code) VALUES(?,?,?,?) ON CONFLICT DO NOTHING', (cid, course, '데이터베이스', course))
        self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'university_id': U, 'department_id': D, 'catalog_id': C}})

    def jobs(self):
        result = job_result()
        # All four fixture skills have equal frequency. Keep SQL in the small
        # representative unknown sample for this SQL-specific contract fixture.
        result['skills'].sort(key=lambda s: (s['name'] != 'SQL', s['name']))
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=result) as model:
            response = self.client.post(self.base + '/job-skill-analysis', json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), model.call_count

    def make(self, refresh=False):
        return self.client.post(self.base + '/roadmap', json={'expected_input_revision': self.revision(), 'refresh': refresh})

    def generated(self, refresh=False):
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=fake_roadmap) as ai:
            response = self.make(refresh)
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json(), ai.call_count

    def sql_answer(self, status):
        snapshot = self.comparison()['job_analysis']['snapshot_id']
        response = self.client.post(self.base + '/skill-comparison/answers', json={
            'expected_input_revision': self.revision(), 'snapshot_id': snapshot, 'skill_name': 'SQL', 'status': status})
        self.assertEqual(response.status_code, 200, response.text)

    def complete_course(self, course=DB_COURSE, catalog=C):
        plan = self.client.get(self.base).json()
        response = self.client.patch(self.base + '/course-selections', json={'catalog_id': catalog,
            'expected_selection_revision': plan['selection_revision'], 'changes': [{'course_id': course, 'is_completed': True}]})
        self.assertEqual(response.status_code, 200, response.text)

    def review_courses(self, missing=False):
        plan = self.client.get(self.base).json()
        response = self.client.post(self.base + '/course-selection-review', json={'catalog_id': C,
            'expected_selection_revision': plan['selection_revision'], 'expected_input_revision': plan['input_revision'], 'reported_missing_courses': missing})
        self.assertEqual(response.status_code, 200, response.text)

    def test_roadmap_personalization_and_completion(self):
        self.doc()
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction):
            item = self.analyze()['experiences'][0]
        self.jobs(); self.answer(item, 'confirmed'); self.sql_answer('no_experience'); self.review_courses()
        a, _ = self.generated()
        self.assertEqual(a['preparation_summary']['confirmed_skills'], ['Python'])
        self.assertIn('SQL', a['preparation_summary']['learning_candidates'])
        self.assertEqual(a['recommended_courses'][0]['course_id'], DB_COURSE)
        self.assertEqual(a['recommended_courses'][0]['description_basis'], 'name_inference')
        self.assertEqual(a['recommended_courses'][0]['recommendation_confidence'], 'limited')
        self.sql_answer('unknown')
        self.answer(item, 'corrected', {'skill_name': 'SQL', 'activity': '쿼리 작성', 'contribution_scope': 'personal'})
        self.complete_course(); self.review_courses()
        b, _ = self.generated()
        self.assertIn('SQL', b['preparation_summary']['confirmed_skills'])
        self.assertEqual(b['recommended_courses'], [])
        self.assertNotEqual(a['roadmap'], b['roadmap'])
        self.assertTrue(self.client.get(f'{self.base}/roadmaps/{a["run_id"]}').json()['is_stale'])

    def test_roadmap_unknown_and_unavailable(self):
        with patch('api.routes.roadmaps.generate_roadmap') as ai:
            limited = self.make().json()
            self.assertEqual(limited['generation_mode'], 'limited_guidance'); ai.assert_not_called()
            self.assertEqual(limited['status'], 'partial')
            self.assertEqual([c['course_id'] for c in limited['recommended_courses']], [DB_COURSE])
            self.assertEqual(limited['preparation_items'], [])
            self.assertTrue(self.make(refresh=True).json()['reused'])
            task = limited['roadmap'][0]['tasks'][0]['task_id']
            response = self.client.patch(f'{self.base}/roadmaps/{limited["run_id"]}/tasks/{task}',
                json={'is_completed': True, 'expected_progress_version': 0})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get(self.base + '/roadmap').json()['progress']['completed'], 1)
        self.jobs()
        self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'catalog_id': None}})
        run, _ = self.generated()
        self.assertEqual(run['course_status'], 'catalog_unavailable')
        self.assertEqual(run['status'], 'partial')
        self.assertEqual(run['recommended_courses'], [])
        self.assertEqual(run['preparation_summary']['learning_candidates'], [])
        self.assertIn('SQL', run['preparation_summary']['skills_to_verify'])
        self.assertEqual(run['roadmap'][0]['skill_targets'][0]['student_status'], 'not_verified')

    def test_roadmap_persistence_cache_progress_refresh(self):
        self.jobs(); run, calls = self.generated(); self.assertEqual(calls, 1)
        rid = run['run_id']; revision = self.revision()
        with patch('api.routes.roadmaps.generate_roadmap') as ai:
            self.assertEqual(self.client.get(self.base + '/roadmap').json()['run_id'], rid)
            self.assertTrue(self.make().json()['reused'])
            changed = self.client.patch(f'{self.base}/roadmaps/{rid}/tasks/task-1', json={'is_completed': True, 'expected_progress_version': 0})
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()['progress']['completed'], 1)
            self.assertEqual(self.revision(), revision)
            self.assertEqual(self.client.get(self.base + '/roadmap').json()['roadmap'][0]['tasks'][0]['progress_version'], 1)
            self.assertEqual(self.client.patch(f'{self.base}/roadmaps/{rid}/tasks/task-1', json={'is_completed': False, 'expected_progress_version': 0}).json()['error'], 'progress_conflict')
            ai.assert_not_called()
        new, _ = self.generated(True)
        self.assertNotEqual(new['run_id'], rid); self.assertEqual(new['progress']['completed'], 0)
        self.assertEqual(len(self.client.get(self.base + '/roadmaps').json()['runs']), 2)

    def test_roadmap_full_basis_invalidation(self):
        self.jobs(); first, _ = self.generated()
        self.review_courses(True)
        second, _ = self.generated()
        self.assertEqual(second['basis']['review_status'], 'partial')
        self.assertNotEqual(first['basis_hash'], second['basis_hash'])
        # Catalog metadata can change without input_revision: still invalidate.
        with closing(connect()) as db:
            db.execute('UPDATE course_catalogs SET scope_description=? WHERE catalog_id=?', (str(uuid.uuid4()), C))
        self.assertTrue(self.client.get(self.base + '/roadmap').json()['is_stale'])
        third, _ = self.generated()
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=self.comparison()['job_analysis']):
            self.client.post(self.base + '/job-skill-analysis', json={'refresh': True})
        self.assertTrue(self.client.get(self.base + '/roadmap').json()['is_stale'])
        fourth, _ = self.generated()
        self.assertNotEqual(third['basis_hash'], fourth['basis_hash'])

    def test_roadmap_deleted_or_reextracted_document_restricts_details(self):
        did = self.doc(); self.jobs(); first, _ = self.generated()
        self.client.post(f'{self.base}/documents/{did}/retry-extraction', json={'expected_input_revision': self.revision()})
        detail = self.client.get(f'{self.base}/roadmaps/{first["run_id"]}').json()
        self.assertTrue(detail['details_restricted']); self.assertNotIn('roadmap', detail); self.assertNotIn('evidence', detail)
        self.assertEqual(self.client.patch(f'{self.base}/roadmaps/{first["run_id"]}/tasks/task-1', json={'is_completed': True, 'expected_progress_version': 0}).json()['error'], 'evidence_unavailable')
        second, _ = self.generated()
        self.client.request('DELETE', f'{self.base}/documents/{did}', json={'expected_input_revision': self.revision()})
        self.assertTrue(self.client.get(f'{self.base}/roadmaps/{second["run_id"]}').json()['details_restricted'])
        history = self.client.get(self.base + '/roadmaps').json()
        self.assertNotIn('evidence_text', str(history)); self.assertNotIn('result_json', str(history))

    def test_roadmap_analysis_completion_invalidates_without_input_change(self):
        self.doc(); self.jobs(); first, _ = self.generated(); revision = self.revision()
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction): self.analyze()
        self.assertEqual(revision, self.revision())
        self.assertTrue(self.client.get(self.base + '/roadmap').json()['is_stale'])
        second, _ = self.generated(); self.assertNotEqual(first['basis_hash'], second['basis_hash'])

    def test_roadmap_outside_completed_preserved(self):
        self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'catalog_id': C2}})
        self.complete_course(OTHER_COURSE, C2)
        self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'catalog_id': C}})
        self.jobs(); run, _ = self.generated()
        self.assertEqual(run['basis']['outside_completed_courses'][0]['course_id'], OTHER_COURSE)
        self.assertEqual(run['recommended_courses'][0]['course_id'], DB_COURSE)
        with closing(connect()) as db:
            self.assertTrue(db.execute('SELECT is_completed FROM input_course_states WHERE request_id=? AND course_id=?', (self.rid, OTHER_COURSE)).fetchone()['is_completed'])

    def test_roadmap_ownership_and_invalid_task(self):
        self.jobs(); run, _ = self.generated()
        other = self.client.post('/api/roadmap-inputs').json()['request_id']
        self.assertEqual(self.client.get(f'/api/roadmap-inputs/{other}/roadmaps/{run["run_id"]}').status_code, 404)
        task = f'{self.base}/roadmaps/{run["run_id"]}/tasks/task-1'
        self.assertEqual(self.client.patch(task.replace('task-1', 'invented'), json={'is_completed': True, 'expected_progress_version': 0}).status_code, 404)
        headers = self.auth.headers() if hasattr(self, 'auth') else {}
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, headers={'Origin': 'http://localhost:3000', **headers}) as stranger:
            if not headers: stranger.post('/api/roadmap-inputs')
            for path in ('/roadmap', '/roadmaps', '/roadmaps/' + run['run_id']):
                self.assertEqual(stranger.get(self.base + path).status_code, 404)
            self.assertEqual(stranger.patch(task, json={'is_completed': True, 'expected_progress_version': 0}).status_code, 404)
            self.assertEqual(stranger.post(self.base + '/roadmap', json={'expected_input_revision': self.revision()}).status_code, 404)

    def test_roadmap_generation_race_and_duplicate(self):
        self.jobs()
        def race(data):
            # Independent request succeeds while the provider is running (no held locks).
            duplicate = self.make()
            self.assertEqual(duplicate.json()['error'], 'generation_in_progress')
            self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'year_level': 3}})
            return fake_roadmap(data)
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=race) as ai:
            response = self.make()
        self.assertEqual(response.status_code, 409, response.text); self.assertEqual(ai.call_count, 1)
        self.assertEqual(response.json()['error'], 'revision_conflict')
        self.assertEqual(self.client.get(self.base + '/roadmap').json()['status'], 'failed')

    def test_roadmap_simultaneous_claims_and_progress(self):
        self.jobs()
        from repositories.roadmaps import RoadmapRepository
        entered, release, provider_entered, provider_release = (threading.Event() for _ in range(4))
        original = RoadmapRepository.create
        def reserve(store, rid, basis):
            entered.set(); self.assertTrue(release.wait(5))
            return original(store, rid, basis)
        def provider(data):
            provider_entered.set(); self.assertTrue(provider_release.wait(5))
            return fake_roadmap(data)
        body = {'expected_input_revision': self.revision()}
        with patch.object(RoadmapRepository, 'create', reserve), patch('api.routes.roadmaps.generate_roadmap', side_effect=provider) as ai, ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.client.post, self.base + '/roadmap', json=body)
            self.assertTrue(entered.wait(5))
            second = pool.submit(self.client.post, self.base + '/roadmap', json=body)
            # Give the second DB transaction a chance to wait on the locked parent.
            threading.Event().wait(.1); release.set()
            self.assertTrue(provider_entered.wait(5))
            duplicate = second.result(5)
            provider_release.set(); saved = first.result(5)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(duplicate.json()['error'], 'generation_in_progress')
        self.assertEqual(saved.status_code, 201, saved.text); self.assertEqual(ai.call_count, 1)
        run = saved.json()
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda _: self.client.patch(f'{self.base}/roadmaps/{run["run_id"]}/tasks/task-1',
                json={'is_completed': True, 'expected_progress_version': 0}), range(2)))
        self.assertEqual(sorted(r.status_code for r in replies), [200, 409])

    def test_roadmap_rate_limit_preserves_and_cools_down(self):
        self.jobs(); previous, _ = self.generated()
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=GeminiError('gemini_rate_limited', 'limited', 503)) as ai:
            self.assertEqual(self.make(True).status_code, 503)
            self.assertEqual(self.make(True).status_code, 503)
            self.assertEqual(ai.call_count, 1)
        self.assertEqual(self.client.get(self.base + '/roadmap').json()['run_id'], previous['run_id'])
        self.assertEqual(self.make().json()['run_id'], previous['run_id'])

    def test_roadmap_expired_lease_recovery(self):
        self.jobs()
        from repositories.roadmaps import RoadmapRepository
        from services.roadmap_generation import capture_basis
        with closing(connect()) as db:
            Repository(db).begin()
            row = db.execute('SELECT * FROM roadmap_inputs WHERE request_id=?', (self.rid,)).fetchone()
            run = RoadmapRepository(db).create(self.rid, capture_basis(db, row))
            db.execute('UPDATE roadmap_runs SET lease_until=? WHERE run_id=?', ('2020-01-01T00:00:00+00:00', run['run_id']))
            db.commit()
        self.assertTrue(self.client.get(self.base + '/roadmap').json()['generation_expired'])
        new, calls = self.generated()
        self.assertEqual(calls, 1); self.assertNotEqual(new['run_id'], run['run_id'])
        old = self.client.get(f'{self.base}/roadmaps/{run["run_id"]}').json()
        self.assertEqual(old['error_code'], 'generation_expired'); self.assertEqual(old['status'], 'failed')

    def test_roadmap_catalog_changed_during_generation(self):
        self.jobs(); revision = self.revision()
        def change(data):
            with closing(connect()) as db:
                db.execute('UPDATE course_catalogs SET scope_description=? WHERE catalog_id=?', (str(uuid.uuid4()), C))
            return fake_roadmap(data)
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=change):
            response = self.make()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['error'], 'revision_conflict')
        self.assertEqual(self.revision(), revision)

    def test_roadmap_invalid_generation_never_saved(self):
        self.jobs()
        def invalid(data):
            output = fake_roadmap(data).model_dump(); output['recommended_courses'][0]['course_id'] = 'invented'
            return output
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=invalid):
            self.assertEqual(self.make().json()['error'], 'gemini_invalid_response')
        with closing(connect()) as db:
            row = db.execute('SELECT status,result_json FROM roadmap_runs WHERE request_id=?', (self.rid,)).fetchone()
            self.assertEqual(row['status'], 'failed'); self.assertIsNone(row['result_json'])

    def test_roadmap_diagnostics_preserve_v2_progress_then_create_new_success(self):
        from copy import deepcopy
        self.jobs()
        def four_tasks(data):
            raw = fake_roadmap(data).model_dump()
            step = deepcopy(raw['roadmap'][-1])
            step.update(step_id='step-4', order=4, depends_on=['step-3'])
            step['tasks'][0].update(task_id='task-4', action='SQL 경험 확인 자료 4를 정리한다.')
            raw['roadmap'].append(step)
            return raw
        with patch('services.roadmap_generation.RULES_VERSION', 'personalized-roadmap-v2'), \
             patch('api.routes.roadmaps.generate_roadmap', side_effect=four_tasks):
            old = self.make().json()
        checked = self.client.patch(f'{self.base}/roadmaps/{old["run_id"]}/tasks/task-1', json={
            'is_completed': True, 'expected_progress_version': 0}).json()
        self.assertEqual(checked['progress'], {'completed': 1, 'total': 4})

        def invalid(data):
            raw = four_tasks(data)
            raw['roadmap'][0]['skill_targets'][0]['student_status'] = 'confirmed_experience'
            raw['roadmap'][0]['reason'] = 'PRIVATE_PROJECT_TEXT_DO_NOT_LOG'
            return raw
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=invalid) as ai, \
             self.assertLogs('api.routes.roadmaps', level='WARNING') as logs:
            response = self.make(True)
        self.assertEqual(ai.call_count, 1)
        self.assertEqual(response.status_code, 502)
        failure = response.json()
        self.assertEqual(failure['error'], 'gemini_invalid_response')
        self.assertEqual(failure['detail_code'], 'experience_status_mismatch')
        self.assertEqual(failure['field_path'], '$.roadmap[0].skill_targets[0].student_status')
        self.assertIn(failure['run_id'], ''.join(logs.output))
        self.assertIn(failure['field_path'], ''.join(logs.output))
        self.assertNotIn('PRIVATE_PROJECT_TEXT_DO_NOT_LOG', ''.join(logs.output))
        restored = self.client.get(self.base + '/roadmap').json()
        self.assertEqual(restored['run_id'], old['run_id'])
        self.assertEqual(restored['progress'], checked['progress'])
        detail = self.client.get(f'{self.base}/roadmaps/{failure["run_id"]}').json()
        self.assertEqual(detail['error_code'], 'gemini_invalid_response')
        self.assertEqual(detail['error_detail_code'], failure['detail_code'])
        with closing(connect()) as db:
            row = db.execute('SELECT result_json,error_code FROM roadmap_runs WHERE run_id=?', (failure['run_id'],)).fetchone()
            self.assertIsNone(row['result_json'])
            self.assertEqual(row['error_code'], 'gemini_invalid_response:experience_status_mismatch')
        new, calls = self.generated(True)
        self.assertEqual(calls, 1)
        self.assertNotEqual(new['run_id'], old['run_id'])
        self.assertEqual(new['rules_version'], 'personalized-roadmap-v9-keyword-experience')
        self.assertEqual(new['progress']['completed'], 0)
        self.assertEqual(self.client.get(f'{self.base}/roadmaps/{old["run_id"]}').json()['progress'], checked['progress'])
        self.assertEqual(len(self.client.get(self.base + '/roadmaps').json()['runs']), 3)


if __name__ == '__main__':
    suite = unittest.TestSuite(RoadmapAPI(name) for name in unittest.defaultTestLoader.getTestCaseNames(RoadmapAPI) if name.startswith('test_roadmap_') or name in ('test_context_only_evidence_never_calls_paid_roadmap_generation', 'test_previous_rules_preserve_reads_evidence_progress_and_explicit_upgrade'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

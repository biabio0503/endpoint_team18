"""Shared SQLite/PostgreSQL API scenarios. Uses only synthetic documents and mocked AI."""
from contextlib import closing
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from fastapi.testclient import TestClient
from app.main import app
from api.domain import now
from config import DB_BACKEND
from repositories.documents import DocumentRepository
from repositories.plans import connect, Repository
from services.gemini import GeminiError
from services.job_skill_analysis import ANALYSIS_VERSION, aggregate_skills, verify_skills
from services.job_skill_schemas import ExtractedSkill
from services.project_experience_schemas import DocumentExperience
from services import project_experience as project_service
from classbridge import DETAILS, classbridge_document, classbridge_extraction


def fake_extraction(document):
    text = document['extracted_text']
    items = []
    for name in ('Python', 'Docker', 'React', 'Postgres'):
        quote = next((q for q in text.split('\n') if name in q), None)
        if quote:
            items.append({'skill_name': name, 'category': 'other', 'activity': name + ' 작업',
                          'contribution_scope': 'personal' if '제가' in quote else 'team' if '팀' in quote else 'unknown',
                          'evidence_text': quote})
    return DocumentExperience(document_id=document['document_id'], extraction_revision=document['extraction_revision'], experiences=items)


def job_result():
    jobs = []
    for number, level, relation in [(1, 'entry', 'direct'), (2, 'senior', 'related')]:
        text = 'Python is required. Python is required. SQL is preferred. Docker is mentioned. PostgreSQL is required.'
        skills, _ = verify_skills({'description_text': text}, [
            ExtractedSkill(name=name, category='other', requirement_type=kind, evidence_text=quote)
            for name, kind, quote in [('Python', 'required', 'Python is required.'), ('Python 3', 'required', 'Python is required.'),
                                     ('SQL', 'preferred', 'SQL is preferred.'), ('Docker', 'mentioned', 'Docker is mentioned.'),
                                     ('PostgreSQL', 'required', 'PostgreSQL is required.')]])
        jobs.append({'job_id': str(number), 'title': 'Data Analyst', 'status': 'success', 'source_url': 'https://himalayas.app/jobs/example',
                     'match_type': relation, 'seniority_group': level, 'verified_skills': skills})
    return {'status': 'success', 'analysis_version': ANALYSIS_VERSION, 'skills': aggregate_skills(jobs), 'job_analyses': jobs,
            'analysis_summary': {'analyzed_jobs': 2, 'failed_jobs': 0, 'skipped_jobs': 0}, 'errors': []}


class ProjectExperienceAPI(unittest.TestCase):
    def setUp(self):
        self.worker = patch('app.main.start_worker', return_value=None)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        headers = {'Origin': 'http://localhost:3000'}
        if DB_BACKEND == 'postgres':
            from postgres_auth_fixture import PostgresTestAuth
            self.auth = PostgresTestAuth().start()
            self.addCleanup(self.auth.stop)
            headers.update(self.auth.headers())
        self.client = TestClient(app, headers=headers)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rid = self.client.post('/api/roadmap-inputs').json()['request_id']
        self.base = '/api/roadmap-inputs/' + self.rid
        self.client.patch(self.base, json={'expected_input_revision': 0, 'changes': {'career_goal': '데이터 분석 분야', 'target_role': '데이터 분석가'}})

    def revision(self):
        return self.client.get(self.base).json()['input_revision']

    def doc(self, text='제가 Python으로 전처리 코드를 작성했습니다.', status='ready', confirmed=False, segments=None):
        did = str(uuid.uuid4())
        with closing(connect()) as db:
            Repository(db).begin()
            docs = DocumentRepository(db)
            docs.create(did, self.rid, 'synthetic.txt', 'text/plain', max(1, len(text)), now())
            if status != 'pending':
                docs.lease(did, 'token', now(), False)
                docs.finish_extraction(docs.get(self.rid, did), 'token', {
                    'text': text, 'segments': segments if segments is not None else [{'start': 0, 'end': len(text), 'paragraph': 1}],
                    'status': status, 'limitations': ['일부 내용 미추출'] if status == 'partial' else [], 'error_code': None}, now())
            if confirmed:
                docs.confirm(did, now())
            docs.bump_input(self.rid, now())
            db.commit()
        return did

    def analyze(self, refresh=False):
        response = self.client.post(self.base + '/project-experience-analysis', json={
            'expected_input_revision': self.revision(), 'refresh': refresh})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer(self, item, status, correction=None):
        body = {'expected_input_revision': self.revision(), 'status': status}
        if correction: body['correction'] = correction
        response = self.client.patch(self.base + '/project-experiences/' + item['experience_id'] + '/confirmation', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def jobs(self):
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=job_result()) as model:
            response = self.client.post(self.base + '/job-skill-analysis', json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), model.call_count

    def comparison(self):
        response = self.client.get(self.base + '/skill-comparison')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_sources_confirm_correction_and_job_snapshot_reuse(self):
        d1 = self.doc('제가 Python으로 전처리 코드를 작성했습니다.\n팀은 Docker 환경을 구성했습니다.')
        d2 = self.doc('제가 Postgres 쿼리를 작성했습니다.\nReact 사용 목록입니다.')
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction) as model:
            analysis = self.analyze()
            self.assertEqual(model.call_count, 2)
            self.assertEqual(self.analyze()['requested_documents'], 0)
            self.assertEqual(model.call_count, 2)
        self.assertEqual({e['document_id'] for e in analysis['experiences']}, {d1, d2})
        jobs, calls = self.jobs()
        self.assertEqual(calls, 1)
        comparisons = {c['skill_name']: c for c in self.comparison()['comparisons']}
        self.assertEqual(comparisons['Python']['student_status'], 'document_supported')
        self.assertEqual(comparisons['SQL']['student_status'], 'not_verified')
        self.assertEqual(comparisons['Docker']['student_status'], 'needs_confirmation')
        self.assertEqual(comparisons['PostgreSQL']['student_status'], 'document_supported')
        requirement = comparisons['Python']['job_requirement']
        self.assertEqual((requirement['mentioned_job_count'], requirement['required_job_count']), (2, 2))
        self.assertEqual(requirement['seniority_distribution'], {'entry': 1, 'mid': 0, 'senior': 1, 'unknown': 0})
        self.assertEqual(comparisons['SQL']['job_requirement']['preferred_job_count'], 2)
        python = next(e for e in analysis['experiences'] if e['skill_name'] == 'Python')
        docker = next(e for e in analysis['experiences'] if e['skill_name'] == 'Docker')
        with patch('services.project_experience.extract_project_experiences') as model:
            self.answer(python, 'confirmed')
            self.assertEqual(self.jobs()[1], 0)
            self.answer(docker, 'unknown')
            correction = {'skill_name': 'Docker', 'activity': '컨테이너를 직접 구성', 'contribution_scope': 'personal', 'role': '환경 구성 담당'}
            changed = self.answer(docker, 'corrected', correction)
            self.assertEqual(self.analyze()['requested_documents'], 0)
            model.assert_not_called()
        saved = next(e for e in changed['experiences'] if e['experience_id'] == docker['experience_id'])
        self.assertEqual(saved['activity'], '팀은 Docker 환경을 구성했습니다.')
        self.assertEqual(saved['user_answer']['correction']['activity'], '컨테이너를 직접 구성')
        comparisons = {c['skill_name']: c for c in self.comparison()['comparisons']}
        self.assertEqual(comparisons['Python']['student_status'], 'confirmed_experience')
        self.assertEqual(comparisons['Docker']['student_status'], 'confirmed_experience')
        self.assertEqual(comparisons['SQL']['student_status'], 'not_verified')
        self.assertEqual(self.jobs()[0]['snapshot_id'], jobs['snapshot_id'])

    def test_corrected_skill_matches_user_statement_not_original_quote(self):
        self.doc()
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction): analysis = self.analyze()
        self.jobs()
        self.answer(analysis['experiences'][0], 'corrected', {'skill_name': 'SQL', 'activity': '쿼리 작성', 'contribution_scope': 'personal'})
        compared = {c['skill_name']: c for c in self.comparison()['comparisons']}
        self.assertEqual(compared['Python']['student_status'], 'not_verified')
        self.assertEqual(compared['SQL']['student_status'], 'confirmed_experience')
        self.assertEqual(compared['SQL']['project_evidence'][0]['match_source'], 'user_correction')
        self.assertIn('Python', compared['SQL']['project_evidence'][0]['evidence_text'])

    def test_eligibility_no_documents_and_partial_confirmation(self):
        for status in ('pending', 'failed', 'needs_ocr'): self.doc(status=status)
        self.doc('   ')
        partial = self.doc(status='partial')
        with patch('services.project_experience.extract_project_experiences') as model:
            result = self.analyze()
            self.assertEqual(result['status'], 'no_documents')
            self.assertEqual(len(result['excluded_documents']), 5)
            model.assert_not_called()
        response = self.client.post(f'{self.base}/documents/{partial}/extractions/1/confirmation', json={'expected_input_revision': self.revision()})
        self.assertEqual(response.status_code, 200)
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction):
            result = self.analyze()
        self.assertEqual(result['analyzed_documents'], 1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['documents'][0]['limitations'], ['일부 내용 미추출'])

    def test_delete_reextract_invalidates_answers_and_older_evidence(self):
        did = self.doc()
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction): analysis = self.analyze()
        item = analysis['experiences'][0]
        self.answer(item, 'confirmed')
        response = self.client.post(f'{self.base}/documents/{did}/retry-extraction', json={'expected_input_revision': self.revision()})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get(self.base + '/project-experience-analysis').json()['experiences'], [])
        stale = self.client.patch(f'{self.base}/project-experiences/{item["experience_id"]}/confirmation', json={'expected_input_revision': self.revision(), 'status': 'confirmed'})
        self.assertEqual(stale.status_code, 409)
        with closing(connect()) as db:
            Repository(db).begin()
            docs = DocumentRepository(db)
            docs.lease(did, 'token', now(), False)
            docs.finish_extraction(docs.get(self.rid, did), 'token', {'text': '제가 Python 코드를 작성했습니다.', 'segments': [], 'limitations': [], 'status': 'ready', 'error_code': None}, now())
            db.commit()
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction): result = self.analyze()
        self.assertIsNone(result['experiences'][0]['user_answer'])
        self.assertEqual(result['experiences'][0]['extraction_revision'], 2)
        response = self.client.request('DELETE', f'{self.base}/documents/{did}', json={'expected_input_revision': self.revision()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(self.base + '/project-experience-analysis').json()['experiences'], [])
        # Extraction cleanup cascades through analysis and answers in both DBs.
        with closing(connect()) as db:
            db.execute('DELETE FROM document_extractions WHERE document_id=?', (did,))
            self.assertEqual(db.execute('SELECT count(*) AS n FROM project_experience_analyses WHERE document_id=?', (did,)).fetchone()['n'], 0)

    def test_owner_scope_and_revision_race(self):
        self.doc()
        with TestClient(app, headers={'Origin': 'http://localhost:3000'}) as other:
            self.assertEqual(other.get(self.base + '/project-experience-analysis').status_code, 401)
            if DB_BACKEND == 'postgres': other.headers.update(self.auth.headers())
            other.post('/api/roadmap-inputs')
            for suffix in ('/project-experience-analysis', '/skill-comparison'):
                self.assertEqual(other.get(self.base + suffix).status_code, 404)
            self.assertEqual(other.post(self.base + '/project-experience-analysis', json={'expected_input_revision': self.revision()}).status_code, 404)
        revision = self.revision()
        def change(document):
            response = self.client.patch(self.base, json={'expected_input_revision': revision, 'changes': {'career_goal': '새 목표'}})
            self.assertEqual(response.status_code, 200)
            return fake_extraction(document)
        with patch('services.project_experience.extract_project_experiences', side_effect=change):
            response = self.client.post(self.base + '/project-experience-analysis', json={'expected_input_revision': revision})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get(self.base + '/project-experience-analysis').json()['experiences'], [])
        with patch('services.project_experience.extract_project_experiences') as model:
            response = self.client.post(self.base + '/project-experience-analysis', json={'expected_input_revision': revision})
            self.assertEqual(response.status_code, 409)
            model.assert_not_called()

    def test_invalid_model_document_and_cross_document_quote(self):
        self.doc('제가 Python 코드를 작성했습니다.')
        self.doc('팀은 Docker 환경을 구성했습니다.')
        def invented(document):
            result = fake_extraction(document)
            return result.model_copy(update={'document_id': 'another-users-document'})
        with patch('services.project_experience.extract_project_experiences', side_effect=invented):
            result = self.analyze()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['experiences'], [])
        def cross_quote(document):
            result = fake_extraction(document)
            result.experiences[0].evidence_text = '팀은 Docker 환경을 구성했습니다.' if 'Python' in document['extracted_text'] else '제가 Python 코드를 작성했습니다.'
            return result
        with patch('services.project_experience.extract_project_experiences', side_effect=cross_quote):
            result = self.analyze()
        self.assertEqual(result['experiences'], [])
        self.assertTrue(all(e['code'] == 'evidence_not_in_source' for e in result['errors']))

    def test_partial_failure_rate_limit_and_retry_only_missing_document(self):
        for _ in range(3): self.doc()
        calls = []
        def extract(document):
            calls.append(document['document_id'])
            if len(calls) == 2: raise GeminiError('gemini_rate_limited', 'quota')
            return fake_extraction(document)
        with patch('services.project_experience.extract_project_experiences', side_effect=extract):
            result = self.analyze()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['analyzed_documents'], 1)
        item = result['experiences'][0]
        self.answer(item, 'confirmed')
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction) as model:
            result = self.analyze()
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result['analyzed_documents'], 3)
        self.assertEqual(next(e for e in result['experiences'] if e['experience_id'] == item['experience_id'])['user_confirmation'], 'confirmed')

    def test_explicit_no_experience_and_invalidation_when_documents_change(self):
        jobs, _ = self.jobs()
        compared = self.comparison()
        self.assertEqual(compared['project_analysis']['status'], 'no_documents')
        self.assertTrue(all(c['student_status'] == 'not_verified' for c in compared['comparisons']))
        def answer(status, skill='SQL'):
            return self.client.post(self.base + '/skill-comparison/answers', json={
                'expected_input_revision': self.revision(), 'snapshot_id': jobs['snapshot_id'], 'skill_name': skill, 'status': status})
        self.assertEqual(answer('no_experience', 'invented').status_code, 422)
        self.assertEqual(answer('no_experience').status_code, 200)
        c = next(c for c in self.comparison()['comparisons'] if c['skill_name'] == 'SQL')
        self.assertEqual((c['student_status'], c['preparation_candidate']), ('no_experience', 'consider_learning'))
        self.assertEqual(answer('unknown').status_code, 200)
        self.assertEqual(next(c for c in self.comparison()['comparisons'] if c['skill_name'] == 'SQL')['student_status'], 'needs_confirmation')
        self.doc()
        self.assertEqual(next(c for c in self.comparison()['comparisons'] if c['skill_name'] == 'SQL')['student_status'], 'not_verified')
        self.assertEqual(self.jobs()[1], 0)
        self.client.patch(self.base, json={'expected_input_revision': self.revision(), 'changes': {'target_role': '백엔드 개발자'}})
        self.assertEqual(self.comparison()['job_analysis']['status'], 'not_started')
        self.assertEqual(self.jobs()[1], 1)

    def test_partial_job_cache_and_failed_refresh_preserve_verified_result(self):
        result = job_result()
        result['status'] = 'partial'
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=result):
            saved = self.client.post(self.base + '/job-skill-analysis', json={}).json()
        self.assertEqual(self.jobs()[1], 0)
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value={'status': 'error', 'errors': [{'code': 'gemini_rate_limited'}]}):
            retry = self.client.post(self.base + '/job-skill-analysis', json={'refresh': True}).json()
        self.assertEqual(saved['snapshot_id'], retry['snapshot_id'])
        self.assertEqual(retry['refresh_error']['status'], 'error')
        self.assertEqual(self.comparison()['status'], 'partial')
        self.assertEqual(self.client.post(self.base + '/job-skill-analysis', json={'skills': []}).status_code, 422)

    def test_classbridge_details_context_and_nonfatal_adjustments(self):
        fixture = classbridge_document()
        self.doc(fixture['extracted_text'], segments=fixture['segments'])
        with patch('services.project_experience.extract_project_experiences', side_effect=classbridge_extraction):
            result = self.analyze()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['documents'][0]['errors'], [])
        self.assertEqual(result['verified_experiences'], 13)
        for detail in DETAILS.values():
            item = next(i for i in result['experiences'] if i['activity'] == detail)
            self.assertEqual(item['contribution_scope'], 'personal')
            self.assertEqual(item['contribution_basis']['source'], 'document')
            self.assertEqual(item['contribution_basis']['context'][0]['text'], '본인이 직접 수행한 작업')
            self.assertIsNone(item['user_confirmation'])
            self.assertIsNone(item['role'])
            self.assertIsNone(item['output'])
        # Result-screen comparison must preserve detailed work alongside table summaries.
        jobs = job_result()
        template = jobs['skills'][0]
        jobs['skills'] = [{**template, 'name': name} for name in DETAILS]
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value=jobs):
            self.client.post(self.base + '/job-skill-analysis', json={})
        for comparison in self.comparison()['comparisons']:
            self.assertEqual(comparison['student_status'], 'document_supported')
            self.assertIn(DETAILS[comparison['skill_name']], [e['activity'] for e in comparison['project_evidence']])

    def test_refresh_reuses_extraction_and_never_reassigns_answers(self):
        fixture = classbridge_document()
        did = self.doc(fixture['extracted_text'], segments=fixture['segments'])
        with patch('services.project_experience.extract_project_experiences', side_effect=classbridge_extraction):
            old = self.analyze()
        details = [i for i in old['experiences'] if i['activity'] in DETAILS.values()]
        self.answer(details[0], 'confirmed')
        correction = {'skill_name': 'SQL', 'activity': '직접 작성한 쿼리', 'contribution_scope': 'personal'}
        self.answer(details[1], 'corrected', correction)
        def reordered(document):
            self.assertEqual(document['extracted_text'], fixture['extracted_text'])
            self.assertEqual(document['segments'], fixture['segments'])
            result = classbridge_extraction(document)
            result.experiences.reverse()
            return result
        with patch('services.project_experience.extract_project_experiences', side_effect=reordered) as model, \
             patch('services.document_ocr.DocumentOCR.read', side_effect=AssertionError('OCR must not run')) as ocr, \
             patch('worker.documents.request_work', side_effect=AssertionError('No extraction scheduled')) as worker:
            cached = self.analyze()
            self.assertEqual(cached['requested_documents'], 0)
            self.assertEqual(sum(i['user_answer'] is not None for i in cached['experiences']), 2)
            refreshed = self.analyze(refresh=True)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(refreshed['requested_documents'], 1)
            self.assertEqual(refreshed['reused_documents'], 0)
            self.assertEqual(refreshed['document_basis'], old['document_basis'])
            self.assertTrue(all(i['extraction_revision'] == 1 and i['user_answer'] is None for i in refreshed['experiences']))
            self.assertFalse({i['experience_id'] for i in old['experiences']} & {i['experience_id'] for i in refreshed['experiences']})
            self.assertEqual(self.analyze()['requested_documents'], 0)
            self.assertEqual(model.call_count, 1)
            ocr.assert_not_called()
            worker.assert_not_called()
        stale = self.client.patch(self.base + '/project-experiences/' + details[0]['experience_id'] + '/confirmation',
            json={'expected_input_revision': self.revision(), 'status': 'confirmed'})
        self.assertEqual(stale.status_code, 409)
        with closing(connect()) as db:
            self.assertEqual(DocumentRepository(db).get(self.rid, did)['extraction_revision'], 1)
            self.assertEqual(db.execute('SELECT count(*) AS n FROM document_extractions WHERE document_id=?', (did,)).fetchone()['n'], 1)
            # Prior user statements remain with their original analysis for audit.
            self.assertEqual(db.execute('SELECT count(*) AS n FROM project_experience_answers WHERE analysis_id=?',
                                        (old['experiences'][0]['analysis_id'],)).fetchone()['n'], 2)

    def test_version_upgrade_and_failed_refresh_preserve_answer_boundaries(self):
        self.doc('제가 Python 코드를 작성했습니다.\n팀은 Docker 환경을 구성했습니다.')
        with patch.object(project_service, 'PROJECT_VERSION', 'project-experience-v1'), \
             patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction):
            legacy = self.analyze()
            self.answer(legacy['experiences'][0], 'confirmed')
            self.answer(legacy['experiences'][1], 'corrected', {
                'skill_name': 'Python', 'activity': '개인 자동화', 'contribution_scope': 'personal'})
        with patch('services.project_experience.extract_project_experiences', side_effect=fake_extraction) as model, \
             patch('services.document_ocr.DocumentOCR.read', side_effect=AssertionError('OCR must not run')) as ocr:
            before = self.client.get(self.base + '/project-experience-analysis').json()
            self.assertEqual(before['status'], 'not_started')
            model.assert_not_called()
            upgraded = self.analyze()
            self.assertEqual(model.call_count, 1)
            self.assertTrue(upgraded['analysis_version'].startswith('project-experience-v2:'))
            self.assertTrue(all(i['user_answer'] is None for i in upgraded['experiences']))
            ocr.assert_not_called()
        item = upgraded['experiences'][0]
        self.answer(item, 'confirmed')
        with patch('services.project_experience.extract_project_experiences', side_effect=GeminiError('gemini_timeout', 'timeout')):
            failed = self.analyze(refresh=True)
        self.assertEqual(failed['refresh_errors'][0]['code'], 'gemini_timeout')
        self.assertEqual(failed['status'], 'success')
        self.assertEqual(failed['experiences'][0]['experience_id'], item['experience_id'])
        self.assertEqual(failed['experiences'][0]['user_confirmation'], 'confirmed')
        self.assertEqual(self.client.post(self.base + '/project-experience-analysis', json={
            'expected_input_revision': self.revision(), 'refresh': 'true'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()

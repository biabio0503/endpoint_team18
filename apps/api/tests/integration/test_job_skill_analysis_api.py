"""Mock external APIs, real FastAPI ownership/revision checks, isolated SQLite."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class JobSkillAnalysisAPITest(unittest.TestCase):
    def test_owner_revision_and_model_pipeline(self):
        script = r'''
import json
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app.main import app
from services.gemini import GeminiError
from services.job_skill_schemas import RoleInterpretation
origin = {'Origin': 'http://localhost:3000'}
role = RoleInterpretation.model_validate({'status': 'success', 'canonical_role': 'Security Engineer',
    'search_keywords': [{'keyword': 'Security Engineer', 'relation': 'direct'}], 'clarification_message': None})
with TestClient(app, headers=origin) as client:
    rid = client.post('/api/roadmap-inputs').json()['request_id']
    base = '/api/roadmap-inputs/' + rid
    path = base + '/job-skill-analysis'
    assert client.post(path, json={}).status_code == 422
    updated = client.patch(base, json={'expected_input_revision': 0,
        'changes': {'career_goal': '애플리케이션 보안을 연구하고 싶어요', 'target_role': '보안 엔지니어'}}).json()
    assert client.post(path, json={'owner_id': 'forged'}).status_code == 422
    assert client.post(path, json={}, headers={'Origin': 'https://wrong.example'}).status_code == 403
    with TestClient(app, headers=origin) as other, patch('api.routes.job_skill_analysis.analyze_job_skills') as model:
        assert other.post(path, json={}).status_code == 401
        other.post('/api/roadmap-inputs')
        assert other.post(path, json={}).status_code == 404
        model.assert_not_called()
    posting = {'guid': 'https://himalayas.app/companies/example/jobs/security',
               'title': 'Security Engineer', 'description': '<p>Python is required.</p>'}
    sdk = Mock()
    sdk.models.generate_content.side_effect = [
        Mock(text=role.model_dump_json()),
        Mock(text=json.dumps({'jobs': [{'job_id': posting['guid'], 'skills': [{'name': 'Python',
            'category': 'programming_language', 'requirement_type': 'required', 'evidence_text': 'Python is required.'}]}]}))]
    with patch.dict('os.environ', {'GEMINI_API_KEY': 'mock-key'}), patch('google.genai.Client', return_value=sdk), \
         patch('services.himalayas._request_page', side_effect=lambda keyword, page: {'jobs': [posting] if page == 1 else []}):
        response = client.post(path, json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'success' and result['input_revision'] == updated['input_revision']
    assert result['skills'][0]['required_job_count'] == 1
    assert sdk.models.generate_content.call_count == 2
    assert result['skills'][0]['evidence'][0]['source_url'] == posting['guid']

    # Mutate during both phases. The successful concurrent write also proves the
    # network call does not retain the original read transaction/lock.
    for stage in ('keywords', 'extraction'):
        def change_input(*args):
            current = client.get(base).json()
            change = client.patch(base, json={'expected_input_revision': current['input_revision'],
                'changes': {'career_goal': '새로운 보안 목표 ' + str(current['input_revision'])}})
            assert change.status_code == 200, change.text
            if stage == 'keywords': return role
            raise GeminiError('gemini_timeout', 'mock timeout')
        with patch('services.job_skill_analysis.generate_job_keywords', side_effect=change_input if stage == 'keywords' else lambda *args: role), \
             patch('services.himalayas._request_page', side_effect=lambda keyword, page: {'jobs': [posting] if stage == 'extraction' and page == 1 else []}), \
             patch('services.job_skill_analysis.extract_job_skills', side_effect=change_input):
            response = client.post(path, json={})
        assert response.status_code == 409 and response.json()['error'] == 'revision_conflict', response.text

    # No API key is an analysis failure even when the HTTP request itself succeeds.
    with patch.dict('os.environ', {'GEMINI_API_KEY': ''}):
        response = client.post(path, json={})
    assert response.json()['status'] == 'error'
    assert response.json()['errors'][0]['code'] == 'gemini_not_configured'

    with patch('api.routes.jobs.fetch_jobs', return_value={'status': 'success', 'jobs': []}) as legacy:
        assert client.get(base + '/jobs').status_code == 200
        legacy.assert_called_once()
'''
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'analysis.db'),
                       ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
                       ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000')
            proc = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
                                  env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == '__main__': unittest.main()

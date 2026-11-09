"""FastAPI contract checks run with a fresh isolated SQLite database."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FastAPIContractTest(unittest.TestCase):
    def test_lifespan_docs_routes_and_http_contract(self):
        app_dir = Path(__file__).resolve().parents[2]
        script = r'''
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
assert isinstance(app, FastAPI)
expected = {
 '/api/health', '/api/health/db', '/api/reference', '/api/universities',
 '/api/universities/{university_id}/departments', '/api/departments/{department_id}/catalogs',
 '/api/roadmap-inputs', '/api/roadmap-inputs/resume', '/api/roadmap-inputs/{rid}',
 '/api/roadmap-inputs/{rid}/jobs', '/api/roadmap-inputs/{rid}/courses', '/api/roadmap-inputs/{rid}/course-selections',
 '/api/roadmap-inputs/{rid}/course-selection-review', '/api/roadmap-inputs/{rid}/course-recommendations',
 '/api/roadmap-inputs/{rid}/job-skill-analysis',
 '/api/roadmap-inputs/{rid}/documents', '/api/roadmap-inputs/{rid}/documents/{did}',
 '/api/roadmap-inputs/{rid}/documents/{did}/retry-extraction',
 '/api/roadmap-inputs/{rid}/documents/{did}/extractions/{revision}',
 '/api/roadmap-inputs/{rid}/documents/{did}/extractions/{revision}/confirmation'}
with TestClient(app) as c:
    assert c.get('/api/health').json() == {'status': 'ok'}
    assert c.get('/api/health/db').json() == {'status': 'ok'}
    spec = c.get('/openapi.json').json()
    assert expected == set(spec['paths'])
    assert c.get('/docs').status_code == 200
    assert spec['paths']['/api/roadmap-inputs/{rid}']['patch']['requestBody']
    assert spec['paths']['/api/roadmap-inputs/{rid}/documents']['post']['requestBody']['content']['multipart/form-data']
    assert c.post('/api/roadmap-inputs').status_code == 403
    origin = {'Origin': 'http://localhost:3000'}
    created = c.post('/api/roadmap-inputs', headers=origin)
    assert created.status_code == 201 and 'HttpOnly' in created.headers['set-cookie']
    rid = created.json()['request_id']
    resumed = c.get('/api/roadmap-inputs/resume')
    assert resumed.status_code == 200 and resumed.json()['request']['request_id'] == rid
    url = '/api/roadmap-inputs/' + rid
    assert c.patch(url, headers=origin, content='invalid').json()['error'] == 'invalid_json'
    assert c.patch(url, headers=origin, json={'expected_input_revision': True, 'changes': {}}).status_code == 422
    assert c.patch(url, headers=origin, json={'expected_input_revision': 0, 'changes': {'career_goal': 'test'}}).status_code == 200
    assert c.patch(url, headers=origin, json={'expected_input_revision': 0, 'changes': {'career_goal': 'other'}}).status_code == 409
    assert c.request('DELETE', url + '/documents/00000000-0000-0000-0000-000000000000', headers=origin, json={'expected_input_revision': 1}).status_code == 404
    with patch('api.routes.documents.DB_BACKEND', 'postgres'):
        unavailable = c.get(url + '/documents')
        assert unavailable.status_code == 503 and unavailable.json()['error'] == 'feature_unavailable'
    with TestClient(app) as other:
        assert other.get(url).status_code == 401
'''
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'test.db'), ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0', ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000')
            proc = subprocess.run([sys.executable, '-c', script], cwd=app_dir, env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == '__main__': unittest.main()

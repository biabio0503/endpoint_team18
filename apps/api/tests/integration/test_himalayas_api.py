import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ['ROADMAP_DB_BACKEND'] = 'sqlite'
os.environ['ROADMAP_DB_PATH'] = str(Path(TEMP.name) / 'jobs.sqlite3')
os.environ['ROADMAP_INSECURE_LOCAL_COOKIE'] = '1'
os.environ['ROADMAP_AUTO_SEED_DEV'] = '0'
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from fastapi.testclient import TestClient
import main


class JobsAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app, headers={'Origin': 'http://localhost:3000'})
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEMP.cleanup()

    def test_ownership_saved_input_and_revision(self):
        client = self.client
        created = client.post('/api/roadmap-inputs').json()
        rid = created['request_id']
        path = f'/api/roadmap-inputs/{rid}/jobs'
        self.assertEqual(client.get(path).status_code, 422)
        updated = client.patch(f'/api/roadmap-inputs/{rid}', json={'expected_input_revision': 0, 'changes': {'career_goal': '데이터 분석', 'target_role': '데이터 분석가'}})
        self.assertEqual(updated.status_code, 200)
        with patch('api.routes.jobs.fetch_jobs', return_value={'status': 'success', 'jobs': []}) as fetch:
            response = client.get(path + '?limit=5')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['input_revision'], updated.json()['input_revision'])
        fetch.assert_called_once_with('데이터 분석', '데이터 분석가', 5)
        self.assertEqual(client.get(path + '?limit=101').status_code, 422)
        with TestClient(main.app, headers={'Origin': 'http://localhost:3000'}) as other:
            self.assertEqual(other.get(path).status_code, 401)
            other.post('/api/roadmap-inputs')
            self.assertEqual(other.get(path).status_code, 404)
        def update_during_search(*args):
            revision = client.get(f'/api/roadmap-inputs/{rid}').json()['input_revision']
            changed = client.patch(f'/api/roadmap-inputs/{rid}', json={'expected_input_revision': revision, 'changes': {'career_goal': '백엔드'}})
            self.assertEqual(changed.status_code, 200)
            return {'status': 'success', 'jobs': []}
        with patch('api.routes.jobs.fetch_jobs', side_effect=update_during_search):
            self.assertEqual(client.get(path).status_code, 409)


if __name__ == '__main__': unittest.main()

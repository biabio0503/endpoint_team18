import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ['ROADMAP_DB_BACKEND'] = 'sqlite'
os.environ['ROADMAP_DB_PATH'] = str(Path(TEMP.name) / 'recommendations.sqlite3')
os.environ['ROADMAP_INSECURE_LOCAL_COOKIE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import main as api
from scripts import seed_dev
from services.course_recommendations import recommend


class RecommendationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.migrate(); seed_dev.seed()
        from fastapi.testclient import TestClient
        cls.server = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        cls.server.close(); TEMP.cleanup()

    def setUp(self):
        seed_dev.seed()

    def request(self, method, path, data=None, cookie=None):
        headers={'Origin':'http://localhost:3000'}
        if cookie: headers['Cookie']=cookie
        self.server.cookies.clear()
        response=self.server.request(method, '/api'+path, content=json.dumps(data) if data is not None else None, headers=headers)
        return response.status_code, response.json(), response.headers.get('Set-Cookie')

    def setup_plan(self):
        _,plan,cookie=self.request('POST','/roadmap-inputs'); cookie=cookie.split(';')[0]; rid=plan['request_id']
        status,plan,_=self.request('PATCH','/roadmap-inputs/'+rid,{'expected_input_revision':0,'changes':{'career_goal':'데이터 분석','university_id':seed_dev.U,'department_id':seed_dev.D,'catalog_id':seed_dev.C1}},cookie)
        self.assertEqual(status,200)
        return rid,cookie,plan

    def test_owner_scope_completion_and_stale_input(self):
        rid,cookie,plan=self.setup_plan(); path='/roadmap-inputs/'+rid+'/course-recommendations'
        _,_,other=self.request('POST','/roadmap-inputs'); other=other.split(';')[0]
        self.assertEqual(self.request('POST',path,{},other)[0],404)
        self.assertEqual(self.request('POST',path,{},None)[0],401)
        first=seed_dev.rows[0][0]; second=seed_dev.rows[1][0]
        selection={'catalog_id':seed_dev.C1,'expected_selection_revision':plan['selection_revision'],'changes':[{'course_id':first,'is_completed':True}]}
        self.assertEqual(self.request('PATCH','/roadmap-inputs/'+rid+'/course-selections',selection,cookie)[0],200)
        code,result,_=self.request('POST',path,{},cookie)
        self.assertEqual(code,200)
        self.assertNotIn(first, [c['course_id'] for c in result['courses']])
        self.assertIn(second, [c['course_id'] for c in result['courses']])
        self.assertTrue(all(c['completion_state']=='unconfirmed' for c in result['courses']))
        self.assertEqual(self.request('POST',path,{},cookie)[1]['courses'], result['courses'])
        current=self.request('GET','/roadmap-inputs/'+rid,cookie=cookie)[1]
        self.request('PATCH','/roadmap-inputs/'+rid,{'expected_input_revision':current['input_revision'],'changes':{'year_level':3}},cookie)
        def stale(profile,courses,status,**kwargs):
            current=self.request('GET','/roadmap-inputs/'+rid,cookie=cookie)[1]
            self.request('PATCH','/roadmap-inputs/'+rid,{'expected_input_revision':current['input_revision'],'changes':{'career_goal':'머신러닝'}},cookie)
            return []
        with patch('api.routes.recommendations.recommend',side_effect=stale):
            self.assertEqual(self.request('POST',path,{},cookie)[1]['error'],'revision_conflict')

    def test_empty_catalog_and_missing_key(self):
        rid,cookie,_=self.setup_plan(); path='/roadmap-inputs/'+rid+'/course-recommendations'
        with patch.dict(os.environ, {'GEMINI_API_KEY':''}):
            code,result,_=self.request('POST',path,{},cookie)
            self.assertEqual(code,200)
            self.assertTrue(result['courses'])
        # An isolated empty catalog avoids deleting shared fixture courses that
        # other integration scenarios have referenced through course selections.
        empty_id = str(uuid.uuid4())
        with api.closing(api.connect()) as db:
            db.execute('INSERT INTO course_catalogs VALUES(?,?,NULL,?,?,?,?,?,?,NULL,1)',
                       (empty_id, seed_dev.D, 'empty-test', 'empty test catalog', 'unknown', 'test', None, '2026-11-07T00:00:00+00:00'))
            db.commit()
        current = self.request('GET','/roadmap-inputs/'+rid,cookie=cookie)[1]
        self.assertEqual(self.request('PATCH','/roadmap-inputs/'+rid,
                         {'expected_input_revision':current['input_revision'], 'changes':{'catalog_id':empty_id}},cookie)[0],200)
        code,result,_=self.request('POST',path,{},cookie)
        self.assertEqual((code,result['status'],result['courses']),(200,'empty_catalog',[]))

if __name__=='__main__':unittest.main()

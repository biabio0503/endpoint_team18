import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
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
        from uvicorn_test_server import TestServer
        cls.server = TestServer(api.app)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop(); TEMP.cleanup()

    def setUp(self):
        seed_dev.seed()

    def request(self, method, path, data=None, cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers={'Origin':'http://localhost:3000'}
        if cookie: headers['Cookie']=cookie
        conn.request(method, '/api'+path, body=json.dumps(data) if data is not None else None, headers=headers)
        response=conn.getresponse(); result=(response.status,json.loads(response.read()),response.getheader('Set-Cookie'));conn.close();return result

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
        def fake(profile,courses,status):
            return recommend(profile,courses,status,lambda p,c:[first,'not-in-db',second,second])
        with patch('api.routes.recommendations.recommend',side_effect=fake):
            code,result,_=self.request('POST',path,{},cookie)
        self.assertEqual(code,200); self.assertEqual([c['course_id'] for c in result['courses']],[second]); self.assertEqual(result['courses'][0]['completion_state'],'unconfirmed')
        def stale(profile,courses,status):
            current=self.request('GET','/roadmap-inputs/'+rid,cookie=cookie)[1]
            self.request('PATCH','/roadmap-inputs/'+rid,{'expected_input_revision':current['input_revision'],'changes':{'career_goal':'머신러닝'}},cookie)
            return []
        with patch('api.routes.recommendations.recommend',side_effect=stale):
            self.assertEqual(self.request('POST',path,{},cookie)[1]['error'],'revision_conflict')

    def test_empty_catalog_and_missing_key(self):
        rid,cookie,_=self.setup_plan(); path='/roadmap-inputs/'+rid+'/course-recommendations'
        with patch.dict(os.environ, {'GEMINI_API_KEY':''}):
            code,result,_=self.request('POST',path,{},cookie)
            self.assertEqual((code,result['error']),(503,'gemini_not_configured'))
        with api.closing(api.connect()) as db:
            db.execute('DELETE FROM catalog_courses WHERE catalog_id=?',(seed_dev.C1,))
        code,result,_=self.request('POST',path,{},cookie)
        self.assertEqual((code,result['status'],result['courses']),(200,'empty_catalog',[]))

if __name__=='__main__':unittest.main()

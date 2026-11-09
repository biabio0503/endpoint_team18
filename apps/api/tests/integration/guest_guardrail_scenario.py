"""Guest fixes against a disposable DB; external services always mocked."""
from contextlib import closing
import os
import unittest
from unittest.mock import patch
from roadmap_scenario import RoadmapAPI, C, C2, DB_COURSE, OTHER_COURSE
from project_experience_scenario import job_result, fake_extraction
from repositories.plans import connect

class GuestGuardrails(RoadmapAPI):
    def test_failed_jobs_allow_saved_guidance_and_reanalysis(self):
        with patch('api.routes.job_skill_analysis.analyze_job_skills', return_value={'status':'error','skills':[], 'errors':[{'code':'upstream_down'}]}):
            self.assertEqual(self.client.post(self.base+'/job-skill-analysis', json={}).status_code,200)
        with patch('api.routes.roadmaps.generate_roadmap') as ai:
            limited = self.make().json()
            self.assertEqual(limited['generation_mode'],'limited_guidance')
            self.assertEqual(limited['recommended_courses'],[])
            self.assertEqual(limited['evidence'],{})
            self.client.patch(self.base,json={'expected_input_revision':self.revision(),'changes':{'career_goal':'새 관심 분야'}})
            new = self.make().json()
            self.assertNotEqual(new['run_id'],limited['run_id'])
            self.assertTrue(self.client.get(self.base+'/roadmaps/'+limited['run_id']).json()['is_stale'])
            ai.assert_not_called()
        self.jobs()
        self.assertFalse(self.client.get(self.base+'/roadmap').json()['limited_guidance_available'])
        run, calls = self.generated()
        self.assertEqual(calls,1)
        self.assertNotEqual(run['run_id'],new['run_id'])

    def test_job_and_project_inflight_cost_only_once(self):
        def jobs(*args):
            duplicate=self.client.post(self.base+'/job-skill-analysis',json={})
            self.assertEqual(duplicate.status_code,409,duplicate.text)
            self.assertEqual(duplicate.json()['error'],'ai_request_in_progress')
            return job_result()
        with patch('api.routes.job_skill_analysis.analyze_job_skills',side_effect=jobs) as ai:
            self.assertEqual(self.client.post(self.base+'/job-skill-analysis',json={}).status_code,200)
            self.assertTrue(self.client.post(self.base+'/job-skill-analysis',json={}).json()['reused'])
            self.assertEqual(ai.call_count,1)
        self.doc()
        def project(document):
            duplicate=self.client.post(self.base+'/project-experience-analysis',json={'expected_input_revision':self.revision()})
            self.assertEqual(duplicate.status_code,409,duplicate.text)
            return fake_extraction(document)
        with patch('services.project_experience.extract_project_experiences',side_effect=project) as ai:
            self.analyze(); self.analyze()
            self.assertEqual(ai.call_count,1)

    def test_quota_denial_keeps_reads_and_guidance_available(self):
        with patch.dict(os.environ, {'ROADMAP_AI_GUEST_HOURLY_UNITS':'0','ROADMAP_AI_USER_HOURLY_UNITS':'0'}), patch('api.routes.job_skill_analysis.analyze_job_skills') as ai:
            result=self.client.post(self.base+'/job-skill-analysis',json={})
            self.assertEqual(result.status_code,429,result.text)
            self.assertEqual(result.json()['error'],'ai_budget_exceeded')
            self.assertEqual(self.client.get(self.base+'/skill-comparison').status_code,200)
            self.assertEqual(self.make().json()['generation_mode'],'limited_guidance')
            ai.assert_not_called()

    def test_verified_outside_equivalence_and_same_name_remain_distinct(self):
        self.client.patch(self.base,json={'expected_input_revision':self.revision(),'changes':{'catalog_id':C2}})
        self.complete_course(OTHER_COURSE,C2)
        self.client.patch(self.base,json={'expected_input_revision':self.revision(),'changes':{'catalog_id':C}})
        self.jobs()
        run,_=self.generated()
        self.assertEqual(run['recommended_courses'][0]['course_id'],DB_COURSE)
        pair=sorted([DB_COURSE,OTHER_COURSE])
        with closing(connect()) as db:
            db.execute('INSERT INTO verified_course_equivalences VALUES(?,?,?,?,?,?)',(*pair,'substitute','https://example.edu/verified','Synthetic approved mutual substitution','2026-11-09T00:00:00+00:00'))
            db.commit()
        try:
            self.assertTrue(self.client.get(self.base+'/roadmap').json()['is_stale'])
            run,_=self.generated()
            self.assertEqual(run['recommended_courses'],[])
        finally:
            with closing(connect()) as db:
                db.execute('DELETE FROM verified_course_equivalences WHERE course_id=? AND equivalent_course_id=?',pair); db.commit()

    def test_global_quota_atomic_across_owners(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import uuid
        from api.domain import now, Problem
        from services.ai_guard import guarded_call
        owners=[str(uuid.uuid4()),str(uuid.uuid4())]
        with closing(connect()) as db:
            used=db.execute('SELECT COALESCE(SUM(units),0) AS used FROM ai_requests').fetchone()['used']
            for owner in owners:
                db.execute('INSERT INTO session_owners(owner_id,token_digest,expires_at,created_at) VALUES(?,?,?,?)',
                    (owner,uuid.uuid4().hex,'9999-12-31T00:00:00+00:00',now()))
            db.commit()
        barrier=threading.Barrier(2)
        def reserve(owner):
            with closing(connect()) as db:
                barrier.wait(timeout=5)
                try:
                    guarded_call((db,None,{'owner_id':owner}),'parallel','basis',lambda:[],units=2)
                    return 'success'
                except Problem as error:
                    return error.code
        with patch.dict(os.environ,{'ROADMAP_AI_GLOBAL_DAILY_UNITS':str(used+2)}),ThreadPoolExecutor(2) as pool:
            results=list(pool.map(reserve,owners))
        self.assertEqual(sorted(results),['ai_budget_exceeded','success'])

    def test_course_page_clamps_after_selected_filter_removal(self):
        response=self.client.get(self.base+'/courses',params={'catalog_id':C,'page':999,'page_size':20})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['page'],1)
        self.assertEqual(len(response.json()['courses']),1)

if __name__ == '__main__':
    names=[name for name in GuestGuardrails.__dict__ if name.startswith('test_')]
    suite=unittest.TestSuite(GuestGuardrails(name) for name in names)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

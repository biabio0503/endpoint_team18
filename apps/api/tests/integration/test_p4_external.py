import json
from datetime import datetime
from hashlib import sha256
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app'))
import repositories.plans as storage
from repositories.external import ExternalRepository
from services import external_collection as service

class ExternalCollectionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.previous=storage.DB_PATH
        storage.DB_PATH=Path(self.temp.name)/'test.sqlite3';storage.migrate();service.init_fixtures()
    def tearDown(self):
        storage.DB_PATH=self.previous;self.temp.cleanup()
    def run_job(self,source='fixture-jobs',fixture='v1',key=None):
        job_id,created=service.enqueue(source,fixture,key)
        self.assertTrue(created)
        result=service.process_once();self.assertEqual(result['job_id'],job_id)
        return job_id,result
    def rows(self,sql,params=()):
        with closing(storage.connect()) as db:return [dict(r) for r in db.execute(sql,params)]

    def test_recheck_change_restore_and_evidence(self):
        with patch('socket.socket',side_effect=AssertionError('network is forbidden')):
            job,first=self.run_job(key='unique')
            self.assertEqual(first['counts']['new_versions'],1)
            self.assertEqual(service.enqueue('fixture-jobs','v1','unique'),(job,False))
            with self.assertRaises(ValueError):service.enqueue('fixture-jobs','v2','unique')
            first_item=self.rows('SELECT * FROM external_items')[0]
            version=self.rows('SELECT * FROM external_item_versions')[0]
            self.assertEqual(version['version_no'],1);self.assertEqual(version['content_type'],'text/html; charset=utf-8')
            self.assertIn(b'<html',version['raw_content']);self.assertEqual(sha256(version['raw_content']).hexdigest(),version['content_hash'])
            self.assertEqual(version['collection_job_id'],job);self.assertEqual(version['source_url'],first_item['canonical_url'])
            self.assertIsNotNone(datetime.fromisoformat(version['collected_at']).tzinfo);self.assertIsNotNone(datetime.fromisoformat(version['confirmed_at']).tzinfo)
            self.assertEqual(first_item['latest_validation_job_id'],job)
            facts=json.loads(version['source_facts']);segments=json.loads(version['segments'])
            self.assertEqual(facts['required_skills'][0]['text'],'필수: Python 사용 경험')
            self.assertEqual(facts['preferred_skills'][0]['text'],'우대: 데이터베이스 경험')
            for seg in segments:self.assertEqual(version['source_text'][seg['start']:seg['end']],seg['excerpt'])
            self.assertTrue(all(any(seg['segment_id']==v['segment_id'] and seg['excerpt']==v['text'] for seg in segments) for values in facts.values() for v in values))
            _,second=self.run_job();self.assertEqual(second['counts']['unchanged'],1)
            second_item=self.rows('SELECT * FROM external_items')[0]
            self.assertEqual(len(self.rows('SELECT * FROM external_item_versions')),1)
            self.assertEqual(first_item['last_collected_at'],second_item['last_collected_at'])
            self.assertGreaterEqual(second_item['last_confirmed_at'],first_item['last_confirmed_at'])
            _,third=self.run_job(fixture='v2');self.assertEqual(third['counts']['new_versions'],1)
            self.assertEqual(self.rows('SELECT recruitment_status FROM external_items')[0]['recruitment_status'],'closed')
            self.assertEqual(self.rows('SELECT * FROM external_item_versions ORDER BY version_no')[0]['raw_content'],version['raw_content'])
            _,fourth=self.run_job();self.assertEqual(fourth['counts']['new_versions'],1)
            self.assertEqual([r['version_no'] for r in self.rows('SELECT version_no FROM external_item_versions ORDER BY version_no')],[1,2,3])
            self.assertEqual(self.rows('SELECT source_environment FROM external_sources WHERE source_id=?',('fixture-jobs',))[0]['source_environment'],'fixture')

    def test_empty_partial_failure_and_retry(self):
        self.run_job();before=self.rows('SELECT * FROM external_items')[0]
        job,result=self.run_job(fixture='empty')
        self.assertEqual((result['status'],result['coverage_status'],result['counts']['discovered']),('succeeded','complete',0))
        self.assertEqual(self.rows('SELECT * FROM external_items')[0]['last_confirmed_at'],before['last_confirmed_at'])
        _,partial=self.run_job(fixture='partial')
        self.assertEqual((partial['status'],partial['coverage_status'],partial['counts']['failed']),('partial','partial',1))
        after_partial=self.rows('SELECT * FROM external_items')[0]
        job,failed=self.run_job(fixture='failure')
        self.assertEqual((failed['status'],failed['coverage_status'],failed['counts']['discovered']),('failed','unknown',1))
        item=self.rows('SELECT * FROM external_items')[0]
        self.assertEqual(item['check_status'],'failed');self.assertEqual(item['recruitment_status'],'open')
        self.assertEqual(item['last_confirmed_at'],after_partial['last_confirmed_at'])
        self.assertGreaterEqual(item['last_check_attempt_at'],item['last_confirmed_at'])
        self.assertTrue(service.retry(job));self.assertFalse(service.retry(job));result=service.process_once()
        self.assertEqual(result['status'],'failed');self.assertEqual(service.status(job)['attempt_count'],2)

    def test_activity_pdf_and_no_invented_fields(self):
        _,activity=self.run_job('fixture-activities');self.assertEqual(activity['counts']['succeeded'],2)
        data=service.inspect('fixture-activities')['items'];bykind={x['item_kind']:x for x in data}
        self.assertEqual(bykind['competition']['recruitment_status'],'closed')
        self.assertEqual(bykind['extracurricular']['recruitment_status'],'unknown')
        self.assertEqual(bykind['extracurricular']['source_facts']['team_condition'][0]['text'],'팀 조건: 2~4명')
        self.assertEqual(bykind['competition']['source_facts']['deliverables'][0]['text'],'제출물: 아이디어 제안서')
        _,pdf=self.run_job('fixture-pdf');self.assertEqual((pdf['status'],pdf['coverage_status']),('partial','complete'))
        version=self.rows("SELECT * FROM external_item_versions WHERE content_type='application/pdf'")[0]
        self.assertIn('Fixture PDF announcement',version['source_text']);self.assertEqual(json.loads(version['segments'])[0]['page'],1)
        self.assertEqual(json.loads(version['source_facts']),{});self.assertEqual(json.loads(version['recruitment_facts'])['observed_status'],'unknown')

    def test_lease_recovery_and_stale_worker_cannot_publish(self):
        job,_=service.enqueue('fixture-jobs','v1')
        actual=service.ADAPTERS['fixture-jobs'].collect
        def interrupted(scope):
            batch=actual(scope)
            with closing(storage.connect()) as db:db.execute("UPDATE external_collection_jobs SET lease_until='2000-01-01' WHERE collection_job_id=?",(job,))
            return batch
        with patch.object(service.ADAPTERS['fixture-jobs'],'collect',side_effect=interrupted):
            self.assertEqual(service.process_once()['status'],'lease_lost')
        self.assertEqual(self.rows('SELECT * FROM external_items'),[])
        result=service.process_once();self.assertEqual(result['status'],'succeeded');self.assertEqual(service.status(job)['attempt_count'],2)
        self.assertIsNone(service.process_once())

    def test_invalid_evidence_rolls_back_job(self):
        from dataclasses import replace
        actual=service.ADAPTERS['fixture-jobs'].collect
        def bad(scope):
            batch=actual(scope);item=batch.evidence[0]
            broken=replace(item,facts={'required_skills':[{'text':'생성된 허위 요구','segment_id':'seg-0004'}]})
            return replace(batch,evidence=[broken])
        job,_=service.enqueue('fixture-jobs','v1')
        with patch.object(service.ADAPTERS['fixture-jobs'],'collect',side_effect=bad):
            result=service.process_once()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(service.status(job)['coverage_status'],'unknown')
        self.assertEqual(self.rows('SELECT * FROM external_items'),[])
        self.assertEqual(self.rows('SELECT * FROM external_item_versions'),[])

    def test_personal_input_is_untouched_and_live_sources_disabled(self):
        with closing(storage.connect()) as db:
            db.execute("INSERT INTO session_owners(owner_id,token_digest,expires_at,created_at) VALUES('owner','digest','2099-01-01','2026-01-01')")
            db.execute("INSERT INTO roadmap_inputs(request_id,owner_id,career_goal,input_revision,course_selection_revision,created_at,updated_at) VALUES('request','owner','goal',7,4,'2026-01-01','2026-01-01')")
        before=self.rows('SELECT * FROM roadmap_inputs')
        self.run_job();self.assertEqual(self.rows('SELECT * FROM roadmap_inputs'),before)
        with closing(storage.connect()) as db:db.execute("UPDATE external_sources SET source_environment='live' WHERE source_id='fixture-jobs'")
        with self.assertRaises(ValueError):service.enqueue('fixture-jobs','v1')
        with self.assertRaises(ValueError):service.enqueue('unregistered-site','v1')

if __name__=='__main__':unittest.main()

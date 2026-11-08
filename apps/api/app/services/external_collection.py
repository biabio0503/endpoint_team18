"""Offline external collection orchestration with durable leases and atomic publication."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
import uuid
from providers.external import jobs_fixture,activities_fixture,pdf_fixture
from providers.external.fixture_source import SOURCES
from repositories.plans import connect
from repositories.external import ExternalRepository
from services.external_evidence import validate

ADAPTERS={'fixture-jobs':jobs_fixture,'fixture-activities':activities_fixture,'fixture-pdf':pdf_fixture}
LEASE_SECONDS=120

def now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def later(seconds):return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='microseconds')

def init_fixtures():
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE');repo=ExternalRepository(db)
        for source_id,config in SOURCES.items():repo.register_fixture(source_id,config,now())
        db.commit()

def enqueue(source_id,fixture_set,job_key=None):
    config=SOURCES.get(source_id)
    if not config or fixture_set not in config['sets']:raise ValueError('unsupported_fixture_scope')
    if job_key is not None and (not isinstance(job_key,str) or not job_key.strip() or len(job_key)>200):raise ValueError('invalid_job_key')
    scope={'source_environment':'fixture','fixture_set':fixture_set,'source_kinds':list(config['kinds']),'adapter':config['adapter'],'network_access':False}
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE');repo=ExternalRepository(db);source=repo.source(source_id)
        if not source or not source['is_enabled'] or source['source_environment']!='fixture' or source['adapter_name']!=config['adapter']:raise ValueError('source_not_enabled')
        result=repo.enqueue(source_id,job_key or str(uuid.uuid4()),scope,now());db.commit();return result

def claim():
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE');repo=ExternalRepository(db);job=repo.next_job(now())
        if not job:db.commit();return None
        token=str(uuid.uuid4());repo.lease(job['collection_job_id'],token,later(LEASE_SECONDS),now());db.commit();return dict(job),token

def process_once():
    claimed=claim()
    if not claimed:return None
    job,token=claimed;job_id=job['collection_job_id'];source_id=job['source_id'];scope=json.loads(job['scope_snapshot'])
    try:
        with closing(connect()) as db:
            source=ExternalRepository(db).source(source_id)
            config=SOURCES.get(source_id)
            if not source or not config or not source['is_enabled'] or source['source_environment']!='fixture' or source['adapter_name']!=config['adapter'] or scope.get('adapter')!=config['adapter'] or scope.get('network_access') is not False:raise ValueError('source_not_enabled')
        batch=ADAPTERS[source_id].collect(scope)
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE');repo=ExternalRepository(db)
            if not repo.check_lease(job_id,token,now()):db.rollback();return {'job_id':job_id,'status':'lease_lost'}
            counts={'discovered':batch.discovered,'succeeded':0,'failed':len(batch.failures),'new_versions':0,'unchanged':0}
            for item in batch.evidence:
                validate(item)
                is_new=repo.save_observation(source_id,job_id,item,now());counts['succeeded']+=1;counts['new_versions' if is_new else 'unchanged']+=1
            for failure in batch.failures:repo.mark_failure(source_id,failure['source_item_key'],failure['error_code'],now())
            if batch.failures and not batch.evidence:status,coverage='failed','unknown'
            elif batch.coverage!='complete' or any(item.status=='partial' for item in batch.evidence):status,coverage='partial',batch.coverage
            else:status,coverage='succeeded','complete'
            repo.finish(job_id,token,status,coverage,counts,'item_collection_failed' if batch.failures else None,now());db.commit()
        return {'job_id':job_id,'status':status,'coverage_status':coverage,'counts':counts}
    except Exception:
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE');repo=ExternalRepository(db)
            if not repo.check_lease(job_id,token,now()):db.rollback();return {'job_id':job_id,'status':'lease_lost'}
            repo.finish(job_id,token,'failed','unknown',{'discovered':None,'succeeded':0,'failed':None,'new_versions':0,'unchanged':0},'collection_failed',now());db.commit()
        return {'job_id':job_id,'status':'failed','error_code':'collection_failed'}

def retry(job_id):
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE');changed=ExternalRepository(db).retry(job_id);db.commit();return bool(changed)

def status(job_id):
    with closing(connect()) as db:
        row=ExternalRepository(db).job(job_id)
        if not row:return None
        result=dict(row)
        for k in ('scope_snapshot','counts'):result[k]=json.loads(result[k])
        return result

def inspect(source_id):
    with closing(connect()) as db:
        repo=ExternalRepository(db);source=repo.source(source_id)
        if not source:raise ValueError('unknown_source')
        result=repo.inspect(source_id)
        for row in result:
            for key in ('source_facts','recruitment_facts','segments','limitations'):
                if row[key] is not None:row[key]=json.loads(row[key])
        return {'source_id':source_id,'source_environment':source['source_environment'],'items':result}

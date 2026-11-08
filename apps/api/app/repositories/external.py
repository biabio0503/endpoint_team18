"""SQLite persistence for source observations. Never reads or mutates student data."""
from hashlib import sha256
import json
import uuid

def encode(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

class ExternalRepository:
    def __init__(self,db): self.db=db
    def register_fixture(self,source_id,config,now):
        self.db.execute('''INSERT OR IGNORE INTO external_sources(source_id,source_name,base_url,source_kinds,collection_method,source_environment,adapter_name,collection_policy,freshness_ttl_seconds,is_enabled,created_at,updated_at) VALUES(?,?,?,?,?,'fixture',?,?,NULL,1,?,?)''',(source_id,source_id+' (로컬 가상 fixture)','https://fixtures.invalid/',encode(config['kinds']),'curated',config['adapter'],encode({'fixture_sets':config['sets'],'network_access':False}),now,now))
    def source(self,source_id): return self.db.execute('SELECT * FROM external_sources WHERE source_id=?',(source_id,)).fetchone()
    def enqueue(self,source_id,job_key,scope,now):
        existing=self.db.execute('SELECT * FROM external_collection_jobs WHERE source_id=? AND job_key=?',(source_id,job_key)).fetchone()
        if existing:
            if json.loads(existing['scope_snapshot'])!=scope: raise ValueError('job_key_scope_conflict')
            return existing['collection_job_id'],False
        job_id=str(uuid.uuid4())
        self.db.execute("INSERT INTO external_collection_jobs(collection_job_id,source_id,job_key,scope_snapshot,status,coverage_status,counts,created_at) VALUES(?,?,?,?,'queued','unknown',?,?)",(job_id,source_id,job_key,encode(scope),encode({'discovered':None,'succeeded':0,'failed':0,'new_versions':0,'unchanged':0}),now))
        return job_id,True
    def next_job(self,now):
        return self.db.execute("""SELECT * FROM external_collection_jobs WHERE (status='queued' AND (retry_at IS NULL OR retry_at<=?)) OR (status='running' AND lease_until IS NOT NULL AND lease_until<=?) ORDER BY created_at,collection_job_id LIMIT 1""",(now,now)).fetchone()
    def lease(self,job_id,token,until,now):
        self.db.execute("UPDATE external_collection_jobs SET status='running',attempt_count=attempt_count+1,lease_token=?,lease_until=?,started_at=?,finished_at=NULL,error_code=NULL WHERE collection_job_id=?",(token,until,now,job_id))
    def job(self,job_id): return self.db.execute('SELECT * FROM external_collection_jobs WHERE collection_job_id=?',(job_id,)).fetchone()
    def check_lease(self,job_id,token,now):
        return bool(self.db.execute("SELECT 1 FROM external_collection_jobs WHERE collection_job_id=? AND status='running' AND lease_token=? AND lease_until>?",(job_id,token,now)).fetchone())
    def save_observation(self,source_id,job_id,e,now):
        item=self.db.execute('SELECT * FROM external_items WHERE source_id=? AND source_item_key=?',(source_id,e.source_key)).fetchone()
        if item and item['item_kind']!=e.kind:raise ValueError('item_kind_changed')
        if not item:
            item_id=str(uuid.uuid4())
            self.db.execute("INSERT INTO external_items(external_item_id,source_id,source_item_key,canonical_url,item_kind,check_status,recruitment_status,first_seen_at,updated_at) VALUES(?,?,?,?,?,'not_checked','unknown',?,?)",(item_id,source_id,e.source_key,e.url,e.kind,now,now))
            item=self.db.execute('SELECT * FROM external_items WHERE external_item_id=?',(item_id,)).fetchone()
        item_id=item['external_item_id']; content_hash=sha256(e.raw).hexdigest()
        payload={'content_hash':content_hash,'parser_version':e.parser_version,'url':e.url,'title':e.title,'source_text':e.source_text,'segments':e.segments,'facts':e.facts,'recruitment':e.recruitment,'status':e.status,'limitations':e.limitations}
        fingerprint=sha256(encode(payload).encode()).hexdigest()
        latest=self.db.execute('SELECT * FROM external_item_versions WHERE item_version_id=? AND external_item_id=?',(item['latest_version_id'],item_id)).fetchone() if item['latest_version_id'] else None
        new_version=not latest or latest['version_fingerprint']!=fingerprint
        observed=e.observed_at
        if new_version:
            vid=str(uuid.uuid4()); number=(latest['version_no']+1) if latest else 1
            self.db.execute('''INSERT INTO external_item_versions(item_version_id,external_item_id,collection_job_id,version_no,content_hash,version_fingerprint,parser_version,source_url,title,content_type,raw_content,source_text,segments,source_facts,recruitment_facts,parse_status,limitations,collected_at,confirmed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(vid,item_id,job_id,number,content_hash,fingerprint,e.parser_version,e.url,e.title,e.content_type,e.raw,e.source_text,encode(e.segments),encode(e.facts),encode(e.recruitment),e.status,encode(e.limitations),observed,observed,now))
        else: vid=latest['item_version_id']
        self.db.execute("""UPDATE external_items SET canonical_url=?,latest_version_id=?,latest_validation_job_id=?,last_collected_at=CASE WHEN ? THEN ? ELSE last_collected_at END,last_confirmed_at=?,last_check_attempt_at=?,check_status='confirmed',check_error_code=NULL,recruitment_status=?,updated_at=? WHERE external_item_id=?""",(e.url,vid,job_id,int(new_version),observed,observed,observed,e.recruitment['observed_status'],now,item_id))
        return new_version
    def mark_failure(self,source_id,key,error,at):
        if key:self.db.execute("UPDATE external_items SET last_check_attempt_at=?,check_status='failed',check_error_code=?,updated_at=? WHERE source_id=? AND source_item_key=?",(at,error,at,source_id,key))
    def finish(self,job_id,token,status,coverage,counts,error,now):
        self.db.execute('''UPDATE external_collection_jobs SET status=?,coverage_status=?,counts=?,error_code=?,finished_at=?,lease_until=NULL,lease_token=NULL WHERE collection_job_id=? AND lease_token=?''',(status,coverage,encode(counts),error,now,job_id,token))
    def retry(self,job_id):
        return self.db.execute("UPDATE external_collection_jobs SET status='queued',coverage_status='unknown',counts=?,cursor_checkpoint=NULL,retry_at=NULL,lease_until=NULL,lease_token=NULL,finished_at=NULL,error_code=NULL WHERE collection_job_id=? AND status IN ('failed','partial')",(encode({'discovered':None,'succeeded':0,'failed':0,'new_versions':0,'unchanged':0}),job_id)).rowcount
    def inspect(self,source_id):
        rows=self.db.execute('''SELECT i.source_item_key,i.canonical_url,i.item_kind,i.recruitment_status,i.check_status,i.check_error_code,i.last_confirmed_at,i.last_check_attempt_at,v.version_no,v.content_hash,v.parse_status,v.title,v.source_facts,v.recruitment_facts,v.segments,v.limitations FROM external_items i LEFT JOIN external_item_versions v ON v.item_version_id=i.latest_version_id WHERE i.source_id=? ORDER BY i.source_item_key''',(source_id,)).fetchall()
        return [dict(r) for r in rows]

"""Durable local worker: short DB leases prevent duplicate completion after crashes."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import logging
import threading
import time
import uuid
from repositories.p1 import connect
from repositories.documents import DocumentRepository
from providers.document_storage import get_storage
from providers.document_parser import extract

log=logging.getLogger(__name__)
LEASE_SECONDS=120

def timestamp(): return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def later(seconds): return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='microseconds')

def claim():
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE'); t=timestamp()
        repo=DocumentRepository(db); row=repo.next_job(t)
        if not row: db.commit(); return None
        token=str(uuid.uuid4()); cleanup=row['removed_at'] is not None
        repo.lease(row['document_id'],token,later(LEASE_SECONDS),cleanup)
        db.commit(); return dict(row),token,cleanup

def run_once(storage=None):
    job=claim()
    if not job:return False
    row,token,cleanup=job; storage=storage or get_storage(); did=row['document_id']
    if cleanup:
        try:
            storage.delete(row['storage_key'])
            with closing(connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                DocumentRepository(db).finish_cleanup(did,token)
                db.commit()
        except Exception:
            log.exception('document cleanup failed')
            with closing(connect()) as db:
                DocumentRepository(db).fail_cleanup(did,token,later(10))
        return True
    try:
        extension={'application/pdf':'pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx','text/plain; charset=utf-8':'txt'}[row['mime_type']]
        result=extract(extension,storage.read(row['storage_key']))
    except Exception:
        log.exception('document extraction failed')
        result={'text':'','segments':[],'limitations':['파일을 읽는 중 오류가 발생했습니다.'],'status':'failed','error_code':'extraction_failed'}
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        DocumentRepository(db).finish_extraction(row,token,result,timestamp())
        db.commit()
    return True

def cleanup_orphans(storage=None):
    # Only old, server-generated keys are candidates. Active or recorded files are untouched.
    storage=storage or get_storage()
    cutoff=time.time()-3600
    for key in storage.old_keys(cutoff):
        try:
            with closing(connect()) as db:
                if not DocumentRepository(db).has_storage_key(key): storage.delete(key)
        except OSError: log.exception('orphan cleanup failed')

def loop(stop):
    next_orphan_scan=0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_orphan_scan:
                cleanup_orphans(); next_orphan_scan=time.monotonic()+3600
            if run_once():continue
        except Exception:log.exception('document worker error')
        stop.wait(1)

def start_worker():
    stop=threading.Event(); threading.Thread(target=loop,args=(stop,),daemon=True,name='document-worker').start();return stop

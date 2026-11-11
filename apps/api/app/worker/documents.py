"""Durable local worker: short DB leases prevent duplicate completion after crashes."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import logging
import threading
import time
import uuid
from repositories.plans import connect
from repositories.documents import DocumentRepository
from providers.document_storage import get_storage
from providers.document_parser import extract
from services.document_ocr import DocumentOCR, LeaseLost

log=logging.getLogger(__name__)
LEASE_SECONDS=120
_request_worker_lock = threading.Lock()

def timestamp(): return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def later(seconds): return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='microseconds')

class ExtractionLease:
    """Renew during parsing, Storage I/O and RPCs; fail closed on lost ownership."""
    def __init__(self, row, token):
        self.row=row; self.token=token
        self.stop=threading.Event(); self.lost=threading.Event()
        self.lock=threading.Lock(); self.checked_at=0
    def check(self, force=False):
        with self.lock:
            if self.lost.is_set(): raise LeaseLost()
            # Native DOCX parsing can visit thousands of paragraphs per second.
            if not force and time.monotonic()-self.checked_at < min(5,LEASE_SECONDS/3): return
            try:
                with closing(connect()) as db:
                    valid=DocumentRepository(db).renew(self.row,self.token,timestamp(),later(LEASE_SECONDS))
                if not valid: raise LeaseLost()
                self.checked_at=time.monotonic()
            except Exception:
                self.lost.set(); raise LeaseLost() from None
    def _loop(self):
        while not self.stop.wait(min(20, LEASE_SECONDS / 3)):
            try: self.check(force=True)
            except LeaseLost: return
    def __enter__(self):
        self.check()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='document-lease')
        self.thread.start(); return self
    def __exit__(self, *_):
        self.stop.set(); self.thread.join(timeout=1)

def claim():
    with closing(connect()) as db:
        db.execute('BEGIN' if getattr(db, 'backend', 'sqlite') == 'postgres' else 'BEGIN IMMEDIATE'); t=timestamp()
        repo=DocumentRepository(db); row=repo.next_job(t)
        if not row: db.commit(); return None
        token=str(uuid.uuid4()); cleanup=row['removed_at'] is not None
        repo.lease(row['document_id'],token,later(LEASE_SECONDS),cleanup)
        db.commit(); return dict(row),token,cleanup

def run_once(storage=None, ocr_provider=None):
    job=claim()
    if not job:return False
    row,token,cleanup=job; storage=storage or get_storage(); did=row['document_id']
    if cleanup:
        try:
            storage.delete(row['storage_key'])
            with closing(connect()) as db:
                db.execute('BEGIN' if getattr(db, 'backend', 'sqlite') == 'postgres' else 'BEGIN IMMEDIATE')
                DocumentRepository(db).finish_cleanup(did,token)
                db.commit()
        except Exception:
            log.warning('document cleanup failed')
            with closing(connect()) as db:
                DocumentRepository(db).fail_cleanup(did,token,later(10))
        return True
    try:
        extension={'application/pdf':'pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx','text/plain; charset=utf-8':'txt'}[row['mime_type']]
        with ExtractionLease(row,token) as lease:
            ocr=DocumentOCR(row,token,lambda:lease.check(force=True),provider=ocr_provider)
            result=extract(extension,storage.read(row['storage_key']),ocr=ocr.read,check=lease.check)
            lease.check(force=True)
    except LeaseLost:
        return True
    except Exception:
        log.warning('document extraction failed')
        result={'text':'','segments':[],'limitations':['파일을 읽는 중 오류가 발생했습니다.'],'status':'failed','error_code':'extraction_failed'}
    with closing(connect()) as db:
        db.execute('BEGIN' if getattr(db, 'backend', 'sqlite') == 'postgres' else 'BEGIN IMMEDIATE')
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
        except OSError: log.warning('orphan cleanup failed')

def cleanup_reservation(storage=None):
    """Only inspect expired keys that were reserved before an upload."""
    with closing(connect()) as db:
        db.execute('BEGIN')
        repo = DocumentRepository(db)
        row = repo.next_reservation_cleanup(timestamp())
        if not row:
            db.commit(); return False
        token = str(uuid.uuid4())
        repo.lease_reservation_cleanup(row['storage_key'], token, later(LEASE_SECONDS))
        db.commit()
    try:
        (storage or get_storage()).delete(row['storage_key'])
        with closing(connect()) as db:
            DocumentRepository(db).finish_reservation_cleanup(row['storage_key'], token, later(86400))
    except Exception:
        log.warning('document upload cleanup failed')
        with closing(connect()) as db:
            DocumentRepository(db).fail_reservation_cleanup(row['storage_key'], token, later(60))
    return True

def request_work():
    """Best-effort bounded work; later authenticated requests resume it."""
    if not _request_worker_lock.acquire(blocking=False):
        return
    try:
        cleanup_reservation()
        run_once()
    except Exception:
        log.warning('document request worker failed')
    finally:
        _request_worker_lock.release()

def loop(stop):
    next_orphan_scan=0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_orphan_scan:
                cleanup_orphans(); next_orphan_scan=time.monotonic()+3600
            if run_once():continue
        except Exception:log.warning('document worker error')
        stop.wait(1)

def start_worker():
    stop = threading.Event()
    thread = threading.Thread(target=loop, args=(stop,), daemon=True, name='document-worker')
    thread.start()
    return stop, thread

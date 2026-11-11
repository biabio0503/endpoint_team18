"""Exact 900-unit acceptance cases, using persisted SQLite or isolated PostgreSQL.

All detection is mocked, including independent child processes. These tests never
construct a Google client or use production connection settings.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest

from providers.document_parser import extract
from providers.google_vision_ocr import OCRError
from services import document_ocr as service
from test_document_ocr import ledger, new_job, reader, png, pdf, docx, TEXT


def seed_usage(connect, count, period=None):
    """Historical calls across documents, including failed/uncertain reservations."""
    rows = [new_job(connect) for _ in range((count + 49) // 50)]
    with closing(connect()) as db:
        at = service.budget_time(db)
        if period and service.billing_period(at) != period:
            at = datetime.fromisoformat(period + '-15T12:00:00+00:00')
        db.execute('BEGIN')
        for index in range(count):
            db.execute('''INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
                usage_month,billing_period,status,created_at) VALUES(?,?,1,?,?,?,?)''',
                (rows[index // 50]['document_id'], f'history:{index}', at.strftime('%Y-%m'), period or service.billing_period(at),
                 ('completed', 'failed', 'reserved')[index % 3], at.isoformat()))
        db.commit()


def used(connect, period=None):
    with closing(connect()) as db:
        period = period or service.billing_period(service.budget_time(db))
        return db.execute('SELECT count(*) AS n FROM document_ocr_units WHERE billing_period=?', (period,)).fetchone()['n']


@pytest.mark.parametrize('initial,expected_calls', [(899, 1), (900, 0)])
@pytest.mark.parametrize('configured_limit', ['900', '999999'])
def test_900_hard_boundary(ledger, monkeypatch, initial, expected_calls, configured_limit):
    monkeypatch.setenv('ROADMAP_OCR_MONTHLY_UNIT_LIMIT', configured_limit)
    seed_usage(ledger, initial)
    ocr, provider = reader(ledger)
    if expected_calls:
        assert ocr.read('page:1', png)['text'] == TEXT
    else:
        with pytest.raises(OCRError) as error:
            ocr.read('page:1', png)
        assert error.value.code == 'ocr_budget_exceeded'
    assert provider.detect.call_count == expected_calls
    assert used(ledger) == 900


def concurrent_ten(connect):
    readers = [reader(connect) for _ in range(10)]
    start = threading.Barrier(10)
    def run(item):
        start.wait(timeout=15)
        try:
            item[0].read('page:1', png)
            return 'allowed'
        except OCRError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(run, readers))
    assert results.count('allowed') == 1
    assert results.count('ocr_budget_exceeded') == 9
    assert sum(provider.detect.call_count for _, provider in readers) == 1
    assert used(connect) == 900


def test_899_concurrent_ten_only_one_is_allowed(ledger):
    seed_usage(ledger, 899)
    concurrent_ten(ledger)


def test_timeout_consumes_last_unit_without_repeat_or_other_call(ledger):
    seed_usage(ledger, 899)
    ocr, provider = reader(ledger, Mock(detect=Mock(side_effect=OCRError('ocr_timeout'))))
    for _ in range(3):
        with pytest.raises(OCRError) as error:
            ocr.read('page:1', png)
        assert error.value.code == 'ocr_timeout'
    other, other_provider = reader(ledger)
    with pytest.raises(OCRError) as error:
        other.read('page:1', png)
    assert error.value.code == 'ocr_budget_exceeded'
    assert provider.detect.call_count == 1
    other_provider.detect.assert_not_called()
    assert used(ledger) == 900


def fresh_process(connect, row):
    with closing(connect()) as db:
        backend = getattr(db, 'backend', 'sqlite')
        target = (db.execute('SELECT current_schema() AS name').fetchone()['name'] if backend == 'postgres'
                  else db.execute('PRAGMA database_list').fetchone()['file'])
    script = '''
from contextlib import closing
import json, os, sqlite3, sys
from unittest.mock import Mock
from google.cloud import vision
vision.ImageAnnotatorClient = Mock(side_effect=AssertionError('Real Vision clients forbidden'))
from services import document_ocr as service
backend, target, did = sys.argv[1:]
def connect():
    if backend == 'postgres':
        from repositories.postgres import connect_postgres
        db = connect_postgres(os.environ['ROADMAP_TEST_POSTGRES_URL'])
        db.execute('SET search_path TO "' + target + '"')
        return db
    db = sqlite3.connect(target, isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    db.create_function('ocr_billing_period', 1, service.billing_period, deterministic=True)
    return db
service.connect = connect
with closing(connect()) as db:
    row = dict(db.execute('SELECT * FROM project_documents WHERE document_id=?', (did,)).fetchone())
provider = Mock(detect=Mock(return_value={'text':'synthetic', 'segments':[]}))
ocr = service.DocumentOCR(row, 'token', lambda:None, provider)
try:
    ocr.read('page:1', lambda:b'synthetic')
    status = 'allowed'
except service.OCRError as error:
    status = error.code
with closing(connect()) as db:
    print(json.dumps({'status':status, 'calls':provider.detect.call_count, 'remaining':service.remaining(db)}))
'''
    env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_OCR_PROVIDER='none',
               GOOGLE_APPLICATION_CREDENTIALS='/nonexistent/ocr-test-only.json',
               PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'app'))
    result = subprocess.run([sys.executable, '-c', script, backend, target, row['document_id']],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_process_restart_preserves_usage_and_completed_cache(ledger):
    seed_usage(ledger, 899)
    row = new_job(ledger)
    assert fresh_process(ledger, row) == {'status':'allowed', 'calls':1, 'remaining':0}
    # A new interpreter has no previous in-memory provider, cache or counter.
    assert fresh_process(ledger, row) == {'status':'allowed', 'calls':0, 'remaining':0}
    assert fresh_process(ledger, new_job(ledger)) == {'status':'ocr_budget_exceeded', 'calls':0, 'remaining':0}
    assert used(ledger) == 900


def test_month_rollover_opens_new_budget_without_erasing_history(ledger, monkeypatch):
    clock = [datetime(2026, 12, 1, 7, 59, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(service, 'budget_time', lambda db:clock[0])
    seed_usage(ledger, 899)
    ocr, provider = reader(ledger)
    ocr.read('page:1', png)
    assert used(ledger) == 900
    clock[0] = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
    with closing(ledger()) as db:
        assert service.remaining(db) == 900
    assert ocr.read('page:1', png)['text'] == TEXT
    assert provider.detect.call_count == 1 and used(ledger) == 0
    other, other_provider = reader(ledger)
    other.read('page:1', png)
    assert other_provider.detect.call_count == 1
    assert used(ledger, '2026-11') == 900 and used(ledger, '2026-12') == 1


def test_month_change_between_reservation_and_dispatch_blocks_call(ledger, monkeypatch):
    seed_usage(ledger, 899, period='2026-11')
    moments = iter([datetime(2026, 12, 1, 7, 59, 59, tzinfo=timezone.utc),
                    datetime(2026, 12, 1, 8, tzinfo=timezone.utc)])
    monkeypatch.setattr(service, 'budget_time', lambda db:next(moments))
    ocr, provider = reader(ledger)
    with pytest.raises(OCRError) as error:
        ocr.read('page:1', png)
    assert error.value.code == 'ocr_uncertain'
    provider.detect.assert_not_called()
    assert used(ledger, '2026-11') == 900 and used(ledger, '2026-12') == 0


def test_disabled_provider_keeps_native_parsing_and_no_reservations(ledger, monkeypatch):
    monkeypatch.delenv('ROADMAP_OCR_PROVIDER', raising=False)  # default is also off
    ocr = service.DocumentOCR(new_job(ledger), 'token', lambda:None)
    provider = Mock(side_effect=AssertionError('No OCR client should be constructed'))
    monkeypatch.setattr('google.cloud.vision.ImageAnnotatorClient', provider)
    assert extract('txt', TEXT.encode(), ocr=ocr.read)['text'] == TEXT
    assert extract('pdf', pdf(['text', 'logo']), ocr=ocr.read)['status'] == 'ready'
    assert extract('docx', docx(images=False, text=True), ocr=ocr.read)['status'] == 'ready'
    assert extract('pdf', pdf(['scan']), ocr=ocr.read)['status'] == 'needs_ocr'
    assert used(ledger) == 0
    provider.assert_not_called()


POSTGRES = os.environ.get('ROADMAP_OCR_TEST_BACKEND') == 'postgres'


@pytest.mark.skipif(not POSTGRES, reason='isolated PostgreSQL session isolation regression')
def test_899_concurrent_ten_with_repeatable_read_session_default(ledger, monkeypatch):
    seed_usage(ledger, 899)
    def repeatable_read_connection():
        db = ledger()
        db.execute("SET default_transaction_isolation TO 'repeatable read'")
        return db
    monkeypatch.setattr(service, 'connect', repeatable_read_connection)
    # Ensure every transaction has read a row before anyone acquires the lock.
    # Under an inherited REPEATABLE READ snapshot all ten would see 899.
    snapshots_ready = threading.Barrier(10)
    original_active = service.DocumentOCR._active
    def active(ocr, db):
        original_active(ocr, db)
        snapshots_ready.wait(timeout=15)
    monkeypatch.setattr(service.DocumentOCR, '_active', active)
    concurrent_ten(ledger)


@pytest.mark.skipif(not POSTGRES, reason='isolated PostgreSQL clock regression')
def test_postgres_month_uses_database_clock_even_if_app_clock_is_wrong(ledger, monkeypatch):
    with closing(ledger()) as db:
        expected_month = service.billing_period(service.budget_time(db))
        db.execute("SET TIME ZONE 'Pacific/Kiritimati'")
        assert service.budget_time(db).tzinfo == timezone.utc
    seed_usage(ledger, 899)
    monkeypatch.setattr(service, 'now', lambda:datetime(2000, 1, 1, tzinfo=timezone.utc))
    ocr, provider = reader(ledger)
    ocr.read('page:1', png)
    assert provider.detect.call_count == 1
    assert used(ledger, expected_month) == 900 and used(ledger, '2000-01') == 0


def test_ambiguous_reservation_commit_never_authorizes_a_call(ledger, monkeypatch):
    seed_usage(ledger, 899)
    ocr, provider = reader(ledger)
    class LostCommitResponse:
        def __init__(self):
            self.db = ledger()
            self.backend = getattr(self.db, 'backend', 'sqlite')
        def execute(self, sql, params=()): return self.db.execute(sql, params)
        def close(self): self.db.close()
        def commit(self):
            self.db.commit()
            raise OSError('simulated connection loss after durable commit')
    with monkeypatch.context() as scoped:
        scoped.setattr(service, 'connect', LostCommitResponse)
        with pytest.raises(OCRError) as error:
            ocr.read('page:1', png)
        assert error.value.code == 'ocr_storage_error'
    assert used(ledger) == 900
    with pytest.raises(OCRError) as error:
        ocr.read('page:1', png)
    assert error.value.code == 'ocr_uncertain'
    provider.detect.assert_not_called()

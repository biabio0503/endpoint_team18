"""Pacific billing boundaries and lossless migration of UTC usage records."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from repositories.documents import DocumentRepository
from services import document_ocr as service
from services.ocr_billing import billing_period
from test_document_ocr import ledger, new_job, reader, png
from test_ocr_budget_boundaries import seed_usage, used, concurrent_ten


def instant(value):
    return datetime.fromisoformat(value)


@pytest.mark.parametrize('at,expected', [
    ('2026-01-01T00:00:00+00:00', '2025-12'),
    ('2026-01-01T07:59:59.999999+00:00', '2025-12'),
    ('2026-01-01T08:00:00+00:00', '2026-01'),
    ('2026-07-01T00:00:00+00:00', '2026-06'),
    ('2026-07-01T06:59:59.999999+00:00', '2026-06'),
    ('2026-07-01T07:00:00+00:00', '2026-07'),
    ('2026-07-01T15:59:59+09:00', '2026-06'),
    ('2026-07-01T16:00:00+09:00', '2026-07'),
    ('2026-03-08T09:59:59+00:00', '2026-03'),
    ('2026-03-08T10:00:00+00:00', '2026-03'),
    ('2026-11-01T08:59:59+00:00', '2026-11'),
    ('2026-11-01T09:00:00+00:00', '2026-11'),
])
def test_iana_pacific_period(at, expected):
    assert billing_period(instant(at)) == expected
    assert billing_period(at) == expected  # same conversion used by SQLite migration


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        billing_period(datetime(2026, 7, 1))


# Winter resets at 08:00 UTC; summer resets at 07:00 UTC, never at 00:00 UTC.
BOUNDARIES = [
    ('2026-01-01T00:00:00+00:00', '2026-01-01T08:00:00+00:00', '2025-12', '2026-01'),
    ('2026-07-01T00:00:00+00:00', '2026-07-01T07:00:00+00:00', '2026-06', '2026-07'),
]


@pytest.mark.parametrize('utc_midnight,pacific_midnight,old,new', BOUNDARIES)
def test_utc_month_change_does_not_reset_budget(ledger, monkeypatch, utc_midnight, pacific_midnight, old, new):
    clock = [instant(utc_midnight)]
    monkeypatch.setattr(service, 'budget_time', lambda db:clock[0])
    seed_usage(ledger, 900)
    ocr, provider = reader(ledger)
    with pytest.raises(service.OCRError) as error:
        ocr.read('page:1', png)
    assert error.value.code == 'ocr_budget_exceeded'
    provider.detect.assert_not_called()
    assert used(ledger, old) == 900 and used(ledger, new) == 0
    clock[0] = instant(pacific_midnight)
    with closing(ledger()) as db:
        assert service.remaining(db) == 900
    ocr.read('page:1', png)
    assert provider.detect.call_count == 1
    assert used(ledger, old) == 900 and used(ledger, new) == 1
    with closing(ledger()) as db:
        row = db.execute('SELECT * FROM document_ocr_units WHERE document_id=?', (ocr.row['document_id'],)).fetchone()
        stored = instant(row['created_at']) if isinstance(row['created_at'], str) else row['created_at']
        assert stored.astimezone(timezone.utc) == clock[0]
        assert row['billing_period'] == new
        assert row['usage_month'] == clock[0].strftime('%Y-%m')  # retained legacy field


@pytest.mark.parametrize('utc_midnight,pacific_midnight,old,new', BOUNDARIES)
def test_ten_concurrent_requests_at_pacific_month_boundary(ledger, monkeypatch, utc_midnight, pacific_midnight, old, new):
    clock = [instant(utc_midnight)]
    monkeypatch.setattr(service, 'budget_time', lambda db:clock[0])
    seed_usage(ledger, 900)
    clock[0] = instant(pacific_midnight)
    seed_usage(ledger, 899)
    concurrent_ten(ledger)
    assert used(ledger, old) == 900 and used(ledger, new) == 900


@pytest.mark.parametrize('ledger', ['legacy'], indirect=True)
def test_billing_migration_preserves_utc_keys_status_cache_and_constraints(ledger):
    row = new_job(ledger)
    timestamps = ['2026-07-01T00:00:00+00:00', '2026-07-01T07:00:00+00:00',
                  '2026-12-01T07:59:59.999999+00:00', '2026-12-01T08:00:00+00:00']
    with closing(ledger()) as db:
        for i, at in enumerate(timestamps):
            db.execute('''INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
                usage_month,status,error_code,result_json,created_at) VALUES(?,?,1,?,?,?,?,?)''',
                (row['document_id'], f'image:{i}', at[:7],
                 ('completed', 'failed', 'reserved', 'completed')[i],
                 'ocr_timeout' if i == 1 else None,
                 '{"text":"synthetic OCR cache","segments":[]}' if i in (0, 3) else None, at))
        before = [dict(r) for r in db.execute('SELECT * FROM document_ocr_units ORDER BY unit_key').fetchall()]
        migrate_billing(db)
        after = [dict(r) for r in db.execute('SELECT * FROM document_ocr_units ORDER BY unit_key').fetchall()]
        assert [r['billing_period'] for r in after] == ['2026-06','2026-07','2026-11','2026-12']
        assert [{k:v for k,v in r.items() if k != 'billing_period'} for r in after] == before
        # A stale writer cannot silently create a row in an uncounted period.
        with pytest.raises(Exception):
            db.execute('''INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
                usage_month,status,created_at) VALUES(?,'old-writer',1,'2026-07','reserved',?)''',
                (row['document_id'], timestamps[0]))
        with pytest.raises(Exception):
            db.execute("UPDATE document_ocr_units SET billing_period='2026-07' WHERE unit_key='image:0'")
        if getattr(db, 'backend', 'sqlite') == 'postgres':
            security = db.execute("""SELECT relrowsecurity, has_table_privilege('anon',oid,'SELECT') AS anon_read,
                has_table_privilege('authenticated',oid,'SELECT') AS auth_read
                FROM pg_class WHERE oid='document_ocr_units'::regclass""").fetchone()
            assert security['relrowsecurity'] and not security['anon_read'] and not security['auth_read']
        else:
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    provider = Mock(detect=Mock(side_effect=AssertionError('cached result must not call OCR')))
    ocr = service.DocumentOCR(row, 'token', lambda:None, provider)
    assert ocr.read('image:0', png)['text'] == 'synthetic OCR cache'
    with pytest.raises(service.OCRError) as error:
        ocr.read('image:1', png)
    assert error.value.code == 'ocr_timeout'
    provider.detect.assert_not_called()


def migrate_billing(db):
    root = Path(__file__).resolve().parents[4]
    if getattr(db, 'backend', 'sqlite') == 'postgres':
        schema = db.execute('SELECT current_schema() AS name').fetchone()['name']
        script = (root/'supabase/migrations/20261111021219_document_ocr_billing_period.sql').read_text()
        db.execute('BEGIN')
        db.execute(script.replace('public.', f'"{schema}".'))
        db.commit()
    else:
        script = (root/'apps/api/migrations/010_document_ocr_billing_period.sql').read_text()
        db.executescript('BEGIN IMMEDIATE;\n' + script + '\nCOMMIT;')


@pytest.mark.parametrize('ledger', ['legacy'], indirect=True)
def test_migrated_utc_month_start_rows_still_exhaust_previous_pacific_month(ledger, monkeypatch):
    row = new_job(ledger)
    with closing(ledger()) as db:
        db.execute('BEGIN')
        for i in range(900):
            db.execute('''INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
                usage_month,status,created_at) VALUES(?,?,1,'2026-07','reserved','2026-07-01T00:01:00+00:00')''',
                (row['document_id'], f'historical:{i}'))
        db.commit()
        migrate_billing(db)
    monkeypatch.setattr(service, 'budget_time', lambda db:instant('2026-07-01T06:59:59+00:00'))
    ocr, provider = reader(ledger)
    with pytest.raises(service.OCRError) as error:
        ocr.read('page:1', png)
    assert error.value.code == 'ocr_budget_exceeded'
    provider.detect.assert_not_called()
    assert used(ledger, '2026-06') == 900 and used(ledger, '2026-07') == 0

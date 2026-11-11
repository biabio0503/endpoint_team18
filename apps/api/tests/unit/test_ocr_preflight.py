"""Migration preservation and the read-only operations report on synthetic data."""
from contextlib import closing
import os
from pathlib import Path

import pytest

from test_document_ocr import ledger, new_job
from test_ocr_billing_period import migrate_billing


@pytest.mark.parametrize('ledger', ['legacy'], indirect=True)
def test_billing_migration_preserves_document_and_extraction_history(ledger):
    row = new_job(ledger)
    with closing(ledger()) as db:
        # Keep both an earlier partial extraction and the current ready revision.
        db.execute("UPDATE project_documents SET extraction_revision=2, extraction_status='ready' WHERE document_id=?",
                   (row['document_id'],))
        db.execute('''INSERT INTO document_extractions(document_id,extraction_revision,extraction_status,created_at)
            VALUES(?,2,'pending','2026-11-01T08:00:00+00:00')''', (row['document_id'],))
        for revision, status in [(1, 'partial'), (2, 'ready')]:
            db.execute('''UPDATE document_extractions SET extracted_text=?,extraction_status=?,
                finished_at='2026-11-01T08:01:00+00:00' WHERE document_id=? AND extraction_revision=?''',
                       ('합성 이력 Python API 12', status, row['document_id'], revision))
        def snapshot():
            return {table: [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()]
                    for table in ('project_documents', 'document_extractions')}
        before = snapshot()
        migrate_billing(db)
        assert snapshot() == before


@pytest.mark.skipif(os.environ.get('ROADMAP_OCR_TEST_BACKEND') != 'postgres',
                    reason='read-only report requires isolated PostgreSQL')
@pytest.mark.parametrize('ledger', ['legacy'], indirect=True)
def test_preflight_reports_missing_legacy_and_migrated_schema_without_writes(ledger):
    row = new_job(ledger)
    script = (Path(__file__).resolve().parents[4] / 'supabase/checks/ocr_preflight.sql').read_text()
    with closing(ledger()) as db:
        schema = db.execute('SELECT current_schema() AS name').fetchone()['name']
        # The only target change is public -> the fixture's unique local schema.
        script = script.replace('SET LOCAL search_path TO public, pg_catalog;',
                                f'SET LOCAL search_path TO "{schema}", pg_catalog;')
        notices = []
        db.connection.add_notice_handler(lambda diagnostic: notices.append(diagnostic.message_primary))

        def report():
            notices.clear()
            cursor = db.connection.execute(script)
            while cursor.description is None:
                assert cursor.nextset()
            assert cursor.fetchone()['read_only'] == 'on'
            # Consume all SELECTs and the DO block, fail on any SQL error.
            while cursor.nextset():
                if cursor.description: cursor.fetchall()
            return list(notices)

        db.execute('ALTER TABLE document_ocr_units RENAME TO saved_ocr_units')
        assert 'ocr_preflight table_missing document_ocr_units' in report()
        db.execute('ALTER TABLE saved_ocr_units RENAME TO document_ocr_units')
        db.execute('''INSERT INTO document_ocr_units(document_id,unit_key,extraction_revision,
            usage_month,status,result_json,created_at)
            VALUES(?,'page:1',1,'2026-07','completed',?,'2026-07-01T00:00:00+00:00')''',
                   (row['document_id'], '{"text":"private-synthetic-cache","segments":[]}'))
        before = report()
        assert 'ocr_preflight billing_period_missing' in before
        assert any('"expected_period":"2026-06","units":1' in n for n in before)
        migrate_billing(db)
        after = report()
        assert 'ocr_preflight invalid_billing_period_rows 0' in after
        assert 'ocr_preflight orphan_ocr_units 0' in after
        assert [n for n in before if 'snapshot' in n or 'budget' in n] == [
            n for n in after if 'snapshot' in n or 'budget' in n]
        assert not any('private-synthetic-cache' in n or row['document_id'] in n for n in before + after)
        assert db.execute('SELECT count(*) AS n FROM document_ocr_units').fetchone()['n'] == 1

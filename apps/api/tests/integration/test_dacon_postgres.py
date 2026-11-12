"""Actual PostgreSQL, isolated schema, opt-in localhost DB only. No production resets."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
from threading import Event
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import Mock

import pytest
import psycopg
from psycopg.rows import dict_row
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unit'))
from test_dacon import record
from crawling.dacon.store import Store, KST
from repositories.dacon import load_catalog
from repositories.postgres import PostgresConnection


@pytest.fixture
def database():
    url = os.environ.get('DACON_TEST_DATABASE_URL')
    if not url:
        pytest.skip('DACON_TEST_DATABASE_URL required for isolated PostgreSQL tests')
    parsed = urlsplit(url)
    assert parsed.hostname in ('127.0.0.1', 'localhost') and parsed.path == '/team18_dacon_test'
    schema = 'dacon_test_' + uuid4().hex
    connection = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    migration = Path(__file__).resolve().parents[4] / 'supabase/migrations/20261112012208_dacon_daily_snapshots.sql'
    connection.execute(migration.read_text().replace('public.', schema + '.'))
    connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
    def another():
        conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        return conn
    yield connection, another
    connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    connection.close()


def test_daily_manual_history_failure_empty_and_schedule_idempotence(database):
    db, _ = database
    now = [datetime(2026,11,12,0,10,tzinfo=__import__('datetime').timezone.utc)]
    store = Store(db, lambda: now[0])
    run = store.run(lambda: [record(), record()], 'scheduled')
    assert run['status'] == 'success' and run['collected_count'] == 1 and run['collection_date'] == '2026-11-12'
    collect = Mock(side_effect=AssertionError('must not run'))
    assert store.run(collect, 'scheduled')['status'] == 'already_succeeded'
    assert not collect.called
    manual = store.run(lambda: [record(title='새 데이터 분석 대회')], 'manual')
    assert manual['status'] == 'success'
    assert db.execute('SELECT count(*) AS n FROM dacon_daily_items').fetchone()['n'] == 1
    now[0] += timedelta(days=1)
    assert store.run(lambda: [record()], 'scheduled')['status'] == 'success'
    assert db.execute('SELECT count(*) AS n FROM dacon_daily_snapshots').fetchone()['n'] == 2
    assert db.execute("SELECT payload->>'title' AS title FROM dacon_daily_items WHERE collection_date='2026-11-12'").fetchone()['title'] == '새 데이터 분석 대회'
    before = store.status()['snapshot']
    assert store.run(lambda: [record(), {'id': 'broken'}])['status'] == 'failed'
    assert store.status()['snapshot'] == before
    rows, meta = load_catalog(PostgresConnection(db, psycopg.Error))
    assert rows and meta['status'] == 'partial' and meta['error_code'] == 'last_collection_failed'
    assert store.run(lambda: [])['collected_count'] == 0
    assert load_catalog(PostgresConnection(db, psycopg.Error))[0] == []
    assert store.status()['snapshot']['collected_count'] == 0
    assert store.status(datetime(2026,11,12).date())['snapshot']['collected_count'] == 1


def test_concurrent_manual_scheduled_and_lock_released_after_failure(database):
    db, another = database
    entered, release = Event(), Event()
    def slow():
        entered.set()
        assert release.wait(10)
        return [record()]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(Store(db).run, slow, 'scheduled')
        assert entered.wait(5)
        with another() as other:
            collect = Mock(side_effect=AssertionError('duplicate network request'))
            assert Store(other).run(collect, 'manual')['status'] == 'already_running'
            assert not collect.called
        release.set()
        assert future.result()['status'] == 'success'
    assert Store(db).run(Mock(side_effect=RuntimeError('detail failure')))['status'] == 'failed'
    assert Store(db).run(lambda: [record()])['status'] == 'success'


def test_database_publication_failure_rolls_back_entire_snapshot(database):
    db, _ = database
    store = Store(db)
    assert store.run(lambda: [record()])['status'] == 'success'
    before = store.status()['snapshot']
    db.execute("ALTER TABLE dacon_daily_items ADD CONSTRAINT simulated_failure CHECK (payload->>'title' <> 'reject')")
    assert store.run(lambda: [record(title='reject')])['status'] == 'failed'
    assert store.status()['snapshot'] == before
    assert db.execute("SELECT payload->>'title' AS title FROM dacon_daily_items").fetchone()['title'] == record()['title']


def test_disconnected_owner_recovery(database):
    db, another = database
    with another() as abandoned:
        abandoned.execute('SELECT pg_advisory_lock(%s)', (1800910,))
        old_id = str(uuid4())
        Store(abandoned)._record(old_id, datetime.now(KST).date(), 'manual', 'running', datetime.now(KST))
    assert Store(db).run(lambda: [])['status'] == 'success'
    assert db.execute('SELECT error_code FROM dacon_collection_runs WHERE id=%s', (old_id,)).fetchone()['error_code'] == 'interrupted'


def test_repeated_recommendation_api_reads_only_db_and_ck_survives(database, monkeypatch):
    db, _ = database
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import activities
    from api.dependencies import owned_context
    from services.activity_recommendations import KST
    from crawling.dacon import crawler
    fetch = Mock(side_effect=AssertionError('No student-triggered crawling'))
    monkeypatch.setattr(crawler, 'collect', fetch)
    network = Mock(side_effect=AssertionError('No HTTP requests during recommendation reads'))
    monkeypatch.setattr('socket.socket.connect', network)
    # At this clock the record is open; use far-future explicit fixture dates
    # so a real wall-clock change cannot turn this into a flaky assertion.
    item = record(application_start_at='2020-01-01T00:00:00+09:00', application_end_at='2099-01-01T00:00:00+09:00')
    Store(db).run(lambda: [item])
    adapter = PostgresConnection(db, psycopg.Error)
    plan = {'career_goal': '데이터 분석가', 'target_role': None, 'input_revision': 1}
    repo = Mock(); repo.plan.return_value = plan
    monkeypatch.setattr(activities, 'capture_profile', lambda *args: (plan, 'stable'))
    ck = {'id': 'ck-fixture', 'kind': 'competition', 'title': '데이터 분석 경진대회', 'target': '대학생',
          'period': '상시 접수', 'category': '데이터', 'source': 'contestkorea'}
    monkeypatch.setattr(activities, 'load_contestkorea_catalog', lambda db: ([ck], {'status': 'success', 'kind': 'competition'}))
    app = FastAPI(); app.include_router(activities.router)
    app.dependency_overrides[owned_context] = lambda: (adapter, repo, {'owner_id': 'test'})
    with TestClient(app) as client:
        path = '/api/roadmap-inputs/' + str(uuid4()) + '/activities'
        for _ in range(3):
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert {x['id'] for x in response.json()['activities']} == {'ck-fixture', 'daker:test'}
        assert fetch.call_count == 0
        assert network.call_count == 0
        Store(db).run(Mock(side_effect=RuntimeError('collection failed')))
        assert client.get(path).json()['status'] == 'partial'
        assert len(client.get(path).json()['activities']) == 2
        # Explicitly closed source disappears on successful same-day replacement.
        Store(db).run(lambda: [record(status='종료')])
        assert [x['id'] for x in client.get(path).json()['activities']] == ['ck-fixture']
        Store(db).run(lambda: [{**item, 'application_closed': True}])
        assert [x['id'] for x in client.get(path).json()['activities']] == ['ck-fixture']

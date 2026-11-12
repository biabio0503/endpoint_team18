from datetime import timedelta
from pathlib import Path
import sys
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unit'))
from test_contestkorea_collection import record, NOW
from test_dacon_postgres import database
from crawling.contestkorea.store import Store
from repositories.postgres import PostgresConnection
from repositories.contestkorea import load_catalog


@pytest.fixture
def ck_database(database):
    db, another = database
    return db, another


def test_filters_and_content_dedupe_across_days_preserve_history(ck_database, monkeypatch):
    monkeypatch.setattr(Store, "recheck", lambda self, records: records)
    db, _ = ck_database
    now = [NOW]
    store = Store(db, lambda: now[0])
    batch = [record(), record(), record(id='future',period='2026.12.01 ~ 2026.12.31'),
             record(id='ended',period='2026.10.01 ~ 2026.10.31'), record(id='child',target='고등학생'),
             record(id='unknown',period='11.01~11.30')]
    assert store.run(lambda: batch, 'scheduled')['collected_count'] == 2
    assert store.run(Mock(side_effect=AssertionError()), 'scheduled')['status'] == 'already_succeeded'
    assert store.run(lambda: batch)['collected_count'] == 2
    now[0] += timedelta(days=1)
    assert store.run(lambda: batch, 'scheduled')['status'] == 'success'
    assert db.execute('SELECT count(*) AS n FROM contestkorea_daily_items').fetchone()['n'] == 4
    assert db.execute('SELECT count(*) AS n FROM contestkorea_item_versions').fetchone()['n'] == 2
    assert store.run(lambda: [record(title='새 데이터 분석 대회')])['status'] == 'success'
    assert db.execute('SELECT count(*) AS n FROM contestkorea_item_versions').fetchone()['n'] == 3
    rows, meta = load_catalog(PostgresConnection(db, psycopg.Error))
    assert len(rows) == 2 and any(r['title'] == '새 데이터 분석 대회' for r in rows)
    assert store.status(NOW.date())['snapshot']['collected_count'] == 2
    before = store.status()['snapshot']
    assert store.run(Mock(side_effect=RuntimeError('provider failed')))['status'] == 'failed'
    assert store.status()['snapshot'] == before
    assert load_catalog(PostgresConnection(db, psycopg.Error))[1]['status'] == 'partial'
    assert store.run(lambda: [])['collected_count'] == 0
    assert len(load_catalog(PostgresConnection(db, psycopg.Error))[0]) == 2
    # Current-day superseded content is reclaimed; historical versions remain.
    assert db.execute('SELECT count(*) AS n FROM contestkorea_item_versions').fetchone()['n'] == 2


def test_concurrency_and_publication_rollback(ck_database):
    db, another = ck_database
    entered, release = Event(), Event()
    def slow():
        entered.set()
        assert release.wait(10)
        return [record()]
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(Store(db, lambda: NOW).run, slow, 'scheduled')
        assert entered.wait(5)
        with another() as other:
            collect = Mock(side_effect=AssertionError('no duplicate collection'))
            assert Store(other,lambda: NOW).run(collect)['status'] == 'already_running'
            collect.assert_not_called()
        release.set()
        assert active.result()['status'] == 'success'
    store = Store(db, lambda: NOW)
    before = store.status()['snapshot']
    db.execute("ALTER TABLE contestkorea_item_versions ADD CONSTRAINT reject_test CHECK (payload->>'title' <> 'reject')")
    assert store.run(lambda: [record(title='reject')])['status'] == 'failed'
    assert store.status()['snapshot'] == before
    assert load_catalog(PostgresConnection(db, psycopg.Error))[0][0]['title'] == record()['title']


def test_api_reads_both_sources_without_network(ck_database, monkeypatch):
    db, _ = ck_database
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import activities
    from api.dependencies import owned_context
    Store(db, lambda: NOW).run(lambda: [record(period='상시 접수'),
        record(id='future', period='2099.01.01 09:00 ~ 2099.02.01')])
    plan = {'career_goal':'데이터 분석가','target_role':None,'input_revision':1}
    repo = Mock(); repo.plan.return_value = plan
    monkeypatch.setattr(activities, 'capture_profile', lambda *args: (plan,'same'))
    network = Mock(side_effect=AssertionError('No student-triggered HTTP'))
    monkeypatch.setattr('socket.socket.connect', network)
    provider = Mock(side_effect=AssertionError('No student-triggered provider'))
    monkeypatch.setattr('providers.external.contestkorea.request_json', provider)
    app = FastAPI(); app.include_router(activities.router)
    app.dependency_overrides[owned_context] = lambda: (PostgresConnection(db, psycopg.Error),repo,{'owner_id':'test'})
    with TestClient(app) as client:
        path = '/api/roadmap-inputs/' + str(uuid4()) + '/activities'
        for _ in range(3):
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json()['activities'][0]['source'] == 'contestkorea'
            future, = [item for item in response.json()['activities'] if item['id'] == 'future']
            assert future['status'] == 'upcoming' and future['opens_at'] == '2099-01-01T09:00:00+09:00'
        provider.assert_not_called()
        network.assert_not_called()

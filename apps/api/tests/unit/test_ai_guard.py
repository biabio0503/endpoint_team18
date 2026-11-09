"""Real isolated SQLite reservations, including concurrent independent connections."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from unittest.mock import Mock
import pytest
from api.domain import Problem
from services.ai_guard import guarded_call
from pathlib import Path

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / 'budget.sqlite3'
    def connection():
        db = sqlite3.connect(path, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        return db
    db = connection()
    db.executescript('CREATE TABLE session_owners(owner_id TEXT PRIMARY KEY); CREATE TABLE courses(course_id TEXT PRIMARY KEY);')
    db.executescript((Path(__file__).resolve().parents[2] / 'migrations/008_guest_service_guardrails.sql').read_text())
    db.execute("INSERT INTO session_owners VALUES('a'),('b')")
    for name, value in {'COOLDOWN_SECONDS': '60', 'GUEST_HOURLY_UNITS': '3', 'GUEST_DAILY_UNITS': '4', 'GLOBAL_DAILY_UNITS': '5'}.items():
        monkeypatch.setenv('ROADMAP_AI_' + name, value)
    yield db, connection
    db.close()


def test_cache_cooldown_failure_charge_and_account_rotation(ledger):
    db, _ = ledger
    a, b = (db, None, {'owner_id': 'a'}), (db, None, {'owner_id': 'b'})
    ai = Mock(return_value=['course-a'])
    assert guarded_call(a, 'courses', 'basis', ai, units=2, cache=True) == ['course-a']
    assert guarded_call(a, 'courses', 'basis', ai, units=2, cache=True) == ['course-a']
    assert ai.call_count == 1
    with pytest.raises(Problem, match='잠시 기다린'):
        guarded_call(a, 'courses', 'changed-plan', ai)
    with pytest.raises(Problem) as error:
        guarded_call(a, 'jobs', 'new-plan', ai, units=2)
    assert error.value.code == 'ai_budget_exceeded'
    with pytest.raises(RuntimeError):
        guarded_call(a, 'roadmap', 'basis', lambda: (_ for _ in ()).throw(RuntimeError('provider failed')))
    assert db.execute("SELECT status FROM ai_requests WHERE operation='roadmap'").fetchone()['status'] == 'failed'
    guarded_call(b, 'courses', 'basis', ai, units=2, cache=True)
    with pytest.raises(Problem) as error:
        guarded_call(b, 'roadmap', 'another-account', ai)
    assert error.value.code == 'ai_budget_exceeded'
    assert ai.call_count == 2


def test_parallel_cross_plan_and_operation_requests_single_provider(ledger):
    db, connect = ledger
    entered, release = threading.Event(), threading.Event()
    def provider():
        entered.set()
        assert release.wait(5)
        return []
    def run():
        connection = connect()
        try:
            return guarded_call((connection, None, {'owner_id': 'a'}), 'jobs', 'plan-one', provider)
        finally:
            connection.close()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(run)
        assert entered.wait(5)
        try:
            with pytest.raises(Problem) as error:
                guarded_call((db, None, {'owner_id': 'a'}), 'project', 'plan-two', Mock())
            assert error.value.code == 'ai_request_in_progress'
        finally:
            release.set()
        assert future.result() == []
    assert db.execute('SELECT count(*) AS n FROM ai_requests').fetchone()['n'] == 1


def test_expired_lease_recovers_but_still_counts_budget(ledger, monkeypatch):
    db, _ = ledger
    monkeypatch.setenv('ROADMAP_AI_COOLDOWN_SECONDS', '0')
    ctx = db, None, {'owner_id': 'a'}
    guarded_call(ctx, 'jobs', 'old', lambda: [])
    db.execute("UPDATE ai_requests SET status='running',lease_until='2000-01-01T00:00:00+00:00'")
    guarded_call(ctx, 'jobs', 'new', lambda: [])
    assert db.execute('SELECT SUM(units) AS n FROM ai_requests').fetchone()['n'] == 2

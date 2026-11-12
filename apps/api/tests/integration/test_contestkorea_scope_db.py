"""Regression against an isolated local PostgreSQL, real candidate loader and API."""
from datetime import timedelta
from unittest.mock import Mock

from psycopg.types.json import Jsonb

from test_dacon_postgres import database
from test_contestkorea_collection import NOW, record
from test_activity_review_regressions import api, clock
from crawling.contestkorea.store import Store
from repositories.contestkorea import load_catalog
from repositories.postgres import PostgresConnection
import psycopg


def test_legacy_out_of_scope_is_not_rechecked_or_recommended(database, clock, api, monkeypatch):
    db, _ = database
    store = Store(db, lambda: clock[0])
    good = record(id='good', period='상시 접수')
    assert store.run(lambda: [good, record(id='closed', period='상시 접수', application_closed=True),
                              record(id='cancelled', period='상시 접수', application_cancelled=True)])['status'] == 'success'
    snapshot_before = store.status()['snapshot']
    out = record(id='out', category='스포츠', period='상시 접수')
    failed = record(id='failed', category='기획 • 홍보 • 마케팅', kind='extracurricular', period='상시 접수')
    for item, status, success in [(out, 'active', NOW), (failed, 'pending', None)]:
        db.execute('''INSERT INTO activity_candidates (source,original_id,payload,state,first_seen_at,last_seen_at,
            last_checked_at,last_success_at,next_check_at,check_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            ('contestkorea', item['id'], Jsonb(item), status, NOW, NOW, NOW, success, NOW, 'network_error'))
    before = db.execute("SELECT original_id,payload FROM activity_candidates WHERE original_id IN ('out','failed') ORDER BY original_id").fetchall()
    verify = Mock(side_effect=lambda items: items)
    monkeypatch.setattr(store, 'recheck', verify)
    clock[0] += timedelta(days=1)
    result = store.run(lambda: [])
    assert result['status'] == 'success'
    assert [item['id'] for item in verify.call_args.args[0]] == ['good']
    assert result['metrics']['total_detail_requests'] == 1
    after = db.execute("SELECT original_id,payload FROM activity_candidates WHERE original_id IN ('out','failed') ORDER BY original_id").fetchall()
    assert before == after
    assert db.execute('SELECT count(*) AS n FROM contestkorea_daily_items').fetchone()['n'] == snapshot_before['collected_count']
    items, _ = load_catalog(PostgresConnection(db, psycopg.Error), include_event_context=True)
    assert {item['id'] for item in items} == {'good', 'closed', 'cancelled'}
    assert {item['id'] for item in api()['activities']} == {'good'}

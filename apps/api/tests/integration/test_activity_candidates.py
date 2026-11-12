"""Real PostgreSQL regression tests: discovery, current state and history differ."""
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_contestkorea_postgres import ck_database
from test_dacon_postgres import database
from test_contestkorea_collection import record, NOW
from test_dacon import record as dacon_record
from crawling.activities.batch import Batch
from crawling.contestkorea.store import Store
from crawling.dacon.store import Store as DaconStore
from repositories.contestkorea import load_catalog
from repositories.postgres import PostgresConnection


def current(db, id):
    return db.execute('SELECT * FROM activity_candidates WHERE original_id=%s', (id,)).fetchone()


def test_sliding_ten_retains_one_until_original_confirms_early_close(ck_database, monkeypatch):
    db, _ = ck_database
    clock = [NOW]
    store = Store(db, lambda: clock[0])
    verify = Mock(side_effect=lambda items: items)
    monkeypatch.setattr(store, 'recheck', verify)
    batch = lambda lo,hi: [record(id=str(i)) for i in range(lo,hi)]
    assert store.run(lambda: batch(1,11), 'scheduled')['status'] == 'success'
    clock[0] += timedelta(days=1)
    assert store.run(lambda: batch(2,12), 'scheduled')['status'] == 'success'
    assert [i['id'] for i in verify.call_args.args[0]] == ['1']
    rows, _ = load_catalog(PostgresConnection(db, psycopg.Error))
    assert {r['id'] for r in rows} == {str(i) for i in range(1,12)}
    assert current(db,'1')['missing_since'] and current(db,'1')['last_seen_at'] == NOW
    assert current(db,'1')['last_success_at'] == clock[0]
    assert db.execute("SELECT count(*) AS n FROM contestkorea_daily_items WHERE collection_date=%s", (NOW.date(),)).fetchone()['n'] == 10
    store.run(lambda: batch(2,12))
    assert verify.call_count == 1  # No repeated same-day recheck.
    clock[0] += timedelta(days=1)
    verify.side_effect = lambda items: [{**i,'application_closed':True} for i in items]
    store.run(lambda: batch(2,12))
    assert current(db,'1')['state'] == 'closed'
    assert '1' not in {i['id'] for i in load_catalog(PostgresConnection(db,psycopg.Error))[0]}
    clock[0] += timedelta(days=1)
    store.run(lambda: batch(2,12))
    assert verify.call_count == 2  # Confirmed closed never rechecked.


def test_detail_errors_preserve_success_clock_partial_updates_and_snapshot(ck_database, monkeypatch):
    db, _ = ck_database
    now = [NOW]; store = Store(db,lambda:now[0])
    store.run(lambda:[record(id='1'),record(id='2')])
    before = store.status()['snapshot']
    now[0] += timedelta(days=1)
    broken = {**record(id='1'), 'verification_error':'parse_error', 'period_source':'unverified'}
    result = store.run(lambda:Batch([broken,record(id='2',title='갱신된 데이터 분석 대회')], 'partial', {'parse_failures':1}))
    assert result['status'] == 'partial' and result['metrics']['parse_failures'] == 1
    assert store.status()['snapshot'] == before
    assert current(db,'1')['last_success_at'] == NOW and current(db,'1')['check_status'] == 'parse_error'
    assert current(db,'2')['payload']['title'] == '갱신된 데이터 분석 대회'
    verify = Mock(side_effect=lambda items:[{**i,'verification_error':'network_error'} for i in items])
    monkeypatch.setattr(store,'recheck',verify)
    now[0] += timedelta(days=1)
    result = store.run(lambda:[])
    assert result['status'] == 'partial' and len(verify.call_args.args[0]) == 2
    assert current(db,'1')['last_success_at'] == NOW
    assert current(db,'1')['check_status'] == 'network_error'
    rows, meta = load_catalog(PostgresConnection(db,psycopg.Error))
    assert len(rows) == 2 and all(i['stale'] for i in rows) and meta['status'] == 'partial'
    assert store.status()['snapshot'] == before
    store.run(lambda:[])
    assert verify.call_count == 1


def test_deadlines_unknown_and_cancelled_are_not_rechecked(ck_database, monkeypatch):
    db,_=ck_database
    now=[NOW]; store=Store(db,lambda:now[0])
    store.run(lambda:[record(id='expired',period='2026.11.01 ~ 2026.11.12'),record(id='unknown',period='미정'),
                      record(id='cancelled',application_cancelled=True)])
    now[0] += timedelta(days=1)
    verify=Mock(side_effect=AssertionError('no expired historical HTTP'))
    monkeypatch.setattr(store,'recheck',verify)
    assert store.run(lambda:[])['status']=='success'
    assert current(db,'expired')['state']=='expired'
    assert current(db,'unknown')['state']=='unknown'
    assert current(db,'cancelled')['state']=='cancelled'
    verify.assert_not_called()


def test_real_zero_eligible_does_not_erase_previous_candidates(ck_database, monkeypatch):
    db,_=ck_database
    store=Store(db,lambda:NOW)
    store.run(lambda:[record()])
    monkeypatch.setattr(store,'recheck',lambda items:items)
    result=store.run(lambda:Batch([record(id='child',target='초등학생'),record(id='tbd',period='미정')]))
    assert result['status']=='success' and result['collected_count']==0
    assert len(load_catalog(PostgresConnection(db,psycopg.Error))[0])==1


def test_dacon_missing_candidates_recheck_and_failure_preserves_evidence(database, monkeypatch):
    db,_=database
    now=[NOW]; store=DaconStore(db,lambda:now[0])
    store.run(lambda:[dacon_record()])
    monkeypatch.setattr(store,'recheck',lambda items:[{**i,'verification_error':'network_error'} for i in items])
    now[0] += timedelta(hours=1)
    assert store.run(lambda:[])['status']=='partial'
    assert current(db,'test')['last_success_at']==NOW
    now[0] += timedelta(hours=2)
    monkeypatch.setattr(store,'recheck',lambda items:[{**i,'application_closed':True} for i in items])
    assert store.run(lambda:[])['status']=='success'
    assert current(db,'test')['state']=='closed'


@pytest.mark.parametrize('database',['legacy'],indirect=True)
def test_backfill_all_dates_latest_per_identity_without_fetching_expired_history(database, monkeypatch):
    db,_=database
    from crawling.dacon.validation import validate_records
    for day, items in [(NOW.date(),[dacon_record(),dacon_record(id='daker:expired',url='https://daker.ai/public/hackathons/expired',application_end_at='2026-11-02T00:00:00+09:00')]),
                       (NOW.date()+timedelta(days=1),[])]:
        run_id=str(uuid4())
        db.execute("INSERT INTO dacon_collection_runs(id,collection_date,mode,status,started_at,finished_at,collected_count) VALUES (%s,%s,'manual','success',%s,%s,%s)",(run_id,day,NOW,NOW,len(items)))
        db.execute('INSERT INTO dacon_daily_snapshots VALUES (%s,%s,%s,%s)',(day,run_id,NOW,len(items)))
        for item in validate_records(items):
            db.execute('INSERT INTO dacon_daily_items VALUES (%s,%s,%s,%s)',(day,item['source'],item['original_id'],Jsonb(item)))
    from hashlib import sha256
    import json
    for offset, items in [(0,[record(id='ck1'),record(id='ck2')]),(1,[record(id='ck2',title='갱신된 AI 데이터 대회')])]:
        day=NOW.date()+timedelta(days=offset);rid=str(uuid4())
        db.execute("INSERT INTO contestkorea_collection_runs(id,collection_date,mode,status,started_at,finished_at,collected_count) VALUES (%s,%s,'manual','success',%s,%s,%s)",(rid,day,NOW,NOW,len(items)))
        db.execute('INSERT INTO contestkorea_daily_snapshots VALUES (%s,%s,%s,%s)',(day,rid,NOW,len(items)))
        for item in items:
            digest=sha256(json.dumps(item,sort_keys=True).encode()).digest()
            db.execute('INSERT INTO contestkorea_item_versions VALUES (%s,%s)',(digest,Jsonb(item)))
            db.execute('INSERT INTO contestkorea_daily_items VALUES (%s,%s,%s)',(day,item['id'],digest))
    schema=db.execute('SELECT current_schema() AS n').fetchone()['n']
    path,= (Path(__file__).resolve().parents[4]/'supabase/migrations').glob('*_activity_candidates.sql')
    db.execute(path.read_text().replace('public.',schema+'.'))
    assert current(db,'test')['state']=='pending'
    checked=Mock(side_effect=lambda items:items)
    store=DaconStore(db,lambda:NOW)
    monkeypatch.setattr(store,'recheck',checked)
    assert store.run(lambda:[])['status']=='success'
    assert [i['original_id'] for i in checked.call_args.args[0]]==['test']
    assert current(db,'expired')['state']=='expired'
    assert db.execute('SELECT count(*) AS n FROM dacon_daily_snapshots').fetchone()['n']==2
    assert db.execute('SELECT relrowsecurity FROM pg_class WHERE oid=\'activity_candidates\'::regclass').fetchone()['relrowsecurity']
    assert not db.execute("SELECT has_table_privilege('anon','activity_candidates','SELECT') AS allowed").fetchone()['allowed']

    ckstore=Store(db,lambda:NOW)
    ckcheck=Mock(side_effect=lambda items:items)
    monkeypatch.setattr(ckstore,'recheck',ckcheck)
    assert ckstore.run(lambda:[])['status']=='success'
    assert {i['id'] for i in ckcheck.call_args.args[0]}=={'ck1','ck2'}
    assert current(db,'ck2')['payload']['title']=='갱신된 AI 데이터 대회'
    assert db.execute('SELECT count(*) AS n FROM contestkorea_daily_items WHERE collection_date=%s',(NOW.date()+timedelta(days=1),)).fetchone()['n']==1


def test_reused_closed_detail_does_not_advance_last_success(ck_database):
    db,_=ck_database
    now=[NOW];store=Store(db,lambda:now[0])
    store.run(lambda:[record(id='closed',application_closed=True)])
    now[0]+=timedelta(days=1)
    result=store.run(lambda:[record(id='closed',application_closed=True,detail_reused=True)])
    assert result['status']=='success'
    row=current(db,'closed')
    assert row['last_seen_at']==now[0] and row['last_success_at']==NOW


def test_running_attempt_does_not_mask_previous_incomplete_collection(ck_database):
    db,_=ck_database
    store=Store(db,lambda:NOW)
    store.run(lambda:Batch([record()],status='partial',metrics={'parse_failures':1}))
    store._record(str(uuid4()),NOW.date(),'manual','running',NOW)
    rows,meta=load_catalog(PostgresConnection(db,psycopg.Error))
    assert rows and meta['status']=='partial' and meta['metrics']['parse_failures']==1

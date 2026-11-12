"""044241c review: provider transport fixtures → real stores/Postgres/loaders/API."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_dacon_postgres import database
from test_activity_candidates import current
from test_contestkorea_collection import NOW, record
from test_dacon import record as daker_record
from api.dependencies import owned_context
from api.routes import activities
from crawling.contestkorea.store import Store
from crawling.contestkorea.collector import collect
from crawling.dacon.store import Store as DakerStore
from crawling.dacon.validation import extract_evidence
from providers.external import contestkorea as ck
from repositories.postgres import PostgresConnection
from services.activity_eligibility import KST

URL = 'https://apply.example/challenge'


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return value[0].astimezone(tz)
    for module in ('repositories.activity_candidates', 'services.activity_recommendations',
                   'crawling.contestkorea.collector', 'providers.external.contestkorea'):
        monkeypatch.setattr(module + '.datetime', Frozen)
    return value


@pytest.fixture
def api(database, monkeypatch):
    db, _ = database
    plan = {'career_goal': '데이터 분석가', 'target_role': None, 'input_revision': 1}
    repo = Mock(); repo.plan.return_value = plan
    monkeypatch.setattr(activities, 'capture_profile', lambda *args: (plan, 'stable'))
    app = FastAPI(); app.include_router(activities.router)
    app.dependency_overrides[owned_context] = lambda: (PostgresConnection(db, psycopg.Error), repo, {'owner_id': 'fixture'})
    path = '/api/roadmap-inputs/' + str(uuid4()) + '/activities'
    with TestClient(app) as client:
        def get():
            response = client.get(path)
            assert response.status_code == 200, response.text
            return response.json()
        yield get


def detail(state='접수 중', period='2026.11.01 ~ 2026.11.30', title='데이터 분석 경진대회'):
    return (f'<h1>{title}</h1><table><tr><th>접수 기간</th><td>{period}</td></tr>'
            f'<tr><th>접수 상태</th><td>{state}</td></tr>'
            f'<tr><th>접수하기</th><td><a href="{URL}">신청</a></td></tr></table>').encode()


def transport(monkeypatch, page, period='2026.11.01 ~ 2026.11.30'):
    """Keep actual discovery, verifier and HTML parser; replace only HTTP edges."""
    listing = [{'STR_MEETCODE': 'review', 'STR_MEETING': '데이터 분석 경진대회',
                'STR_MENU': '학문•과학•IT', 'STR_HOST': '주최기관', 'STR_TARGET': '대학생',
                'STR_DATE1': period, 'STR_URL': 'https://www.contestkorea.com/sub/view.php?str_no=review'}]
    monkeypatch.setenv('CONTESTKOREA_API_KEY', 'fixture-secret')
    def request(endpoint, params, key):
        if endpoint == 'menu_info_api.php':
            kind = 'competition' if params['int_gbn'] == '1' else 'extracurricular'
            return [{'STR_BCODE': code, 'STR_IDXWORD': name} for code, name in ck.CONTESTKOREA_CATEGORIES[kind].items()]
        return list(listing) if params['Txt_bcode'].startswith('03') else []
    monkeypatch.setattr(ck, 'request_json', request)
    response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    response.read.side_effect = lambda *args: page[0]
    opener = Mock(); opener.open.return_value = response
    monkeypatch.setattr(ck, 'build_opener', lambda *args: opener)
    return listing, opener


def collect_pair(db, clock, monkeypatch, *, generic=False, date_only=False, relevant_source='contestkorea'):
    listing, _ = transport(monkeypatch, [detail()])
    if relevant_source != 'contestkorea':
        listing[0].update(STR_MEETING='미래 챌린지', STR_MENU='학문•과학•IT')
    store = Store(db, lambda: clock[0])
    assert store.run(lambda: collect(known=store.known_details()))['status'] == 'success'
    period = '2026.11.01 ~ 2026.11.30' if date_only else '2026.11.01 09:00 ~ 2026.11.30 10:00'
    from crawling.dacon import crawler
    title = '미래 챌린지' if generic and relevant_source != 'daker' else '데이터 분석 경진대회'
    body = '[참가 대상]\n누구나\n[일정]\n참가 신청 기간\n' + period
    page = Mock(); page.url = 'https://daker.ai/public/hackathons/test'
    page.goto.return_value.status = 200
    page.locator.return_value.inner_text.return_value = body
    page.evaluate.side_effect = lambda js: [URL] if js == crawler.APPLICATION_LINK_JS else {
        'title': title, 'status': '모집중', 'period': '2026.11.01 ~ 2026.12.31',
        'body': body, 'host': '주최기관', 'prize': '', 'description': '', 'overview': ''}
    monkeypatch.setattr(crawler.time, 'sleep', lambda *args: None)
    cards = crawler.daker_candidates([{'href': page.url, 'title': title, 'status': '모집중'}])
    assert DakerStore(db, lambda: clock[0]).run(lambda: crawler.crawl_details(page, cards))['status'] == 'success'


@pytest.mark.parametrize('hour', [9, 10, 11])
@pytest.mark.parametrize('generic', [False, True])
def test_exact_deadline_through_real_loaders(database, clock, api, monkeypatch, hour, generic):
    db, _ = database
    collect_pair(db, clock, monkeypatch, generic=generic)
    clock[0] = datetime(2026, 11, 30, hour, tzinfo=KST)
    # Include a classified expired row, not only an active row past deadline.
    from crawling.activities.candidates import Candidates
    Candidates(db, ['daker'], clock[0]).classify_history()
    result = api()
    assert len(result['activities']) == (1 if hour == 9 else 0)
    artifact = os.environ.get('ACTIVITY_REVIEW_API_ARTIFACT')
    if artifact and hour == 11:
        Path(artifact).with_name('team18-review-api-closed.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if hour == 9:
        card, = result['activities']
        assert len(card['source_links']) == 2
        assert '10:00 마감' in card['deadline_label'] and '당일 포함' not in card['deadline_label']
        clock[0] = clock[0].replace(minute=58)
        assert api()['valid_until'] == '2026-11-30T10:00:00+09:00'
        if artifact:
            Path(artifact).write_text(json.dumps(result, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('outcome', ['extended', 'closed', 'cancelled', 'network', 'parse'])
def test_extension_survives_stale_listing_next_day(database, clock, api, monkeypatch, outcome):
    db, _ = database
    page = [detail()]
    _, opener = transport(monkeypatch, page, period='2026.11.01 ~ 2026.11.12')
    store = Store(db, lambda: clock[0])
    store.run(lambda: collect(known=store.known_details()))
    before = current(db, 'review')
    assert len(api()['activities']) == 1
    clock[0] += timedelta(days=1)
    if outcome == 'closed': page[0] = detail('접수 마감되었습니다')
    if outcome == 'cancelled': page[0] = detail('대회 취소')
    if outcome == 'parse': page[0] = b'<html>broken structure</html>'
    if outcome == 'network': opener.open.side_effect = OSError('offline')
    result = store.run(lambda: collect(known=store.known_details()))
    assert opener.open.call_count == 2
    row = current(db, 'review')
    assert len(api()['activities']) == (0 if outcome in ('closed', 'cancelled') else 1)
    if outcome in ('extended', 'network', 'parse'):
        assert row['deadline_at'] == before['deadline_at']
    if outcome in ('network', 'parse'):
        assert result['status'] == 'partial'
        assert row['payload'] == before['payload'] and row['last_success_at'] == before['last_success_at']


@pytest.mark.parametrize('phrase,closed', [
    ('접수 중 (정원 충족 시 조기 마감될 수 있습니다)', False),
    ('조기 마감 가능', False), ('예산 소진 시 조기 마감될 수 있습니다', False),
    ('접수 마감 예정', False), ('접수 마감되었습니다', True), ('접수 종료', True),
    ('조기 마감', True), ('대회 취소', True),
    ('조기 마감 가능. 현재 접수 마감되었습니다.', True),
    ('조기 마감 가능하지만 현재 접수 종료', True),
])
def test_status_phrase_collection_to_api(database, clock, api, monkeypatch, phrase, closed):
    db, _ = database
    transport(monkeypatch, [detail(phrase)])
    store = Store(db, lambda: clock[0])
    assert store.run(lambda: collect(known=store.known_details()))['status'] == 'success'
    assert len(api()['activities']) == (0 if closed else 1)


@pytest.mark.parametrize('error', ['network', 'parse'])
def test_first_failure_retries_when_missing_without_faking_success(database, clock, api, monkeypatch, error):
    db, _ = database
    page = [detail() if error == 'network' else b'<html>broken</html>']
    listing, opener = transport(monkeypatch, page)
    if error == 'network': opener.open.side_effect = OSError('offline')
    store = Store(db, lambda: clock[0])
    assert store.run(lambda: collect(known=store.known_details()))['status'] == 'partial'
    row = current(db, 'review')
    assert row is not None
    assert row['last_success_at'] is None and row['first_seen_at'] == clock[0]
    assert row['payload']['url'].endswith('str_no=review')
    assert row['check_status'] == error + '_error' and row['next_check_at'] > clock[0]
    assert api()['activities'] == []
    listing.clear()
    store.run(lambda: collect(known=store.known_details()))
    assert opener.open.call_count == 1  # Retry not due yet.
    clock[0] += timedelta(hours=2)
    store.run(lambda: collect(known=store.known_details()))
    assert opener.open.call_count == 2 and current(db, 'review')['last_success_at'] is None
    clock[0] += timedelta(days=1)
    opener.open.side_effect = None; page[0] = detail()
    assert store.run(lambda: collect(known=store.known_details()))['status'] == 'success'
    assert opener.open.call_count == 3
    assert current(db, 'review')['last_success_at'] == clock[0]
    assert db.execute('SELECT count(*) AS n FROM activity_candidates').fetchone()['n'] == 1
    assert len(api()['activities']) == 1


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('relevant_source', ['contestkorea', 'daker', 'neither'])
def test_relevance_preserves_generic_original_in_api(database, clock, api, monkeypatch, reverse, relevant_source):
    db, _ = database
    collect_pair(db, clock, monkeypatch, generic=True, relevant_source=relevant_source)
    original = activities.recommend
    if reverse:
        monkeypatch.setattr(activities, 'recommend', lambda profile, items, sources:
                            original(profile, list(reversed(items)), sources))
    if relevant_source == 'neither':
        assert api()['activities'] == []
        return
    card, = api()['activities']
    assert len(card['source_links']) == 2
    expected_url = 'str_no=review' if relevant_source == 'contestkorea' else '/test'
    assert all(e['source'] == relevant_source and e['source_url'].endswith(expected_url) for e in card['evidence'])
    assert all(('콘테스트코리아' if relevant_source == 'contestkorea' else '데이커') in reason for reason in card['reasons'])


def test_date_only_daker_is_not_promoted_to_explicit_time(database, clock, api, monkeypatch):
    db, _ = database
    collect_pair(db, clock, monkeypatch, date_only=True)
    clock[0] = datetime(2026, 11, 30, 11, tzinfo=KST)
    card, = api()['activities']
    assert len(card['source_links']) == 2 and card['deadline_precision'] == 'date'
    assert '당일 포함' in card['deadline_label'] and '23:59' not in card['deadline_label']
    assert current(db, 'test')['payload']['application_end_precision'] == 'date'


@pytest.mark.parametrize('database', ['before_retry'], indirect=True)
def test_additive_migration_preserves_populated_candidates_and_history(database, clock, monkeypatch):
    db, _ = database
    store = Store(db, lambda: clock[0])
    monkeypatch.setattr(store, 'recheck', lambda items: items)
    store.run(lambda: [record()])
    clock[0] += timedelta(days=1)
    store.run(lambda: [record(title='갱신된 데이터 대회')])
    tables = ['activity_candidates', 'contestkorea_daily_snapshots', 'contestkorea_daily_items',
              'contestkorea_item_versions', 'contestkorea_collection_runs']
    before = {table: db.execute('SELECT * FROM ' + table).fetchall() for table in tables}
    migration, = (Path(__file__).resolve().parents[4] / 'supabase/migrations').glob('*_activity_candidate_verification_retry.sql')
    schema = db.execute('SELECT current_schema() AS n').fetchone()['n']
    db.execute(migration.read_text().replace('public.', schema + '.'))
    assert {table: db.execute('SELECT * FROM ' + table).fetchall() for table in tables} == before
    failed = record(id='new', verification_error='network_error', period_source='unverified')
    store.run(lambda: [failed])
    assert current(db, 'new')['last_success_at'] is None
    assert current(db, record()['id'])['last_success_at'] == clock[0]
    assert db.execute("SELECT relrowsecurity FROM pg_class WHERE oid='activity_candidates'::regclass").fetchone()['relrowsecurity']
    assert not db.execute("SELECT has_table_privilege('anon','activity_candidates','SELECT') AS allowed").fetchone()['allowed']


def test_daker_first_failure_is_retried_without_listing(database, clock, api, monkeypatch):
    db, _ = database
    from crawling.dacon import crawler
    store = DakerStore(db, lambda: clock[0])
    card = {'id': 'daker:test', 'title': '데이터 분석 경진대회', 'status': '모집중',
            'url': 'https://daker.ai/public/hackathons/test'}
    read = Mock(side_effect=OSError('offline'))
    monkeypatch.setattr(crawler, 'read_daker', read)
    monkeypatch.setattr(crawler.time, 'sleep', lambda *args: None)
    monkeypatch.setattr(store, 'recheck', lambda rows: crawler.crawl_details(None, rows))
    assert store.run(lambda: crawler.crawl_details(None, [card]))['status'] == 'partial'
    assert current(db, 'test')['last_success_at'] is None and api()['activities'] == []
    clock[0] += timedelta(days=1)
    read.side_effect = lambda page, item: daker_record(application_end_at='2026-11-30T10:00:00+09:00')
    assert store.run(lambda: [])['status'] == 'success'
    assert read.call_count == 2 and len(api()['activities']) == 1


def test_unverified_present_in_stale_listing_still_retries(database, clock, api, monkeypatch):
    db, _ = database
    _, opener = transport(monkeypatch, [detail()], period='2026.11.01 ~ 2026.11.12')
    opener.open.side_effect = OSError('offline')
    store = Store(db, lambda: clock[0])
    discover = lambda: collect(known=store.known_details())
    store.run(discover)
    store.run(discover)
    assert opener.open.call_count == 1 and current(db, 'review')['last_success_at'] is None
    clock[0] += timedelta(days=1)
    opener.open.side_effect = None
    assert store.run(discover)['status'] == 'success'
    assert opener.open.call_count == 2 and len(api()['activities']) == 1


@pytest.mark.parametrize('conflict', ['edition', 'url', 'period'])
def test_expired_other_event_cannot_close_same_named_active_event(database, clock, api, monkeypatch, conflict):
    db, _ = database
    collect_pair(db, clock, monkeypatch)
    a, b = current(db, 'review')['payload'], current(db, 'test')['payload']
    if conflict == 'edition':
        a['title'], b['title'] = '제1회 데이터 분석 대회', '제2회 데이터 분석 대회'
    elif conflict == 'url':
        b['official_application_url'] = URL + '/other'
    else:
        b['application_start_at'] = '2026-11-02T09:00:00+09:00'
    Store(db, lambda: clock[0]).run(lambda: [a])
    DakerStore(db, lambda: clock[0]).run(lambda: [b])
    clock[0] = datetime(2026, 11, 30, 11, tzinfo=KST)
    card, = api()['activities']
    assert card['source'] == 'contestkorea' and len(card['source_links']) == 1
    assert '당일 포함' in card['deadline_label']


def test_repeated_api_has_zero_external_requests_after_source_failure(database, clock, api, monkeypatch):
    db, _ = database
    collect_pair(db, clock, monkeypatch, generic=True)
    assert Store(db, lambda: clock[0]).run(Mock(side_effect=OSError('offline')))['status'] == 'failed'
    network = Mock(side_effect=AssertionError('student requests may not collect'))
    monkeypatch.setattr('socket.socket.connect', network)
    monkeypatch.setattr(ck, 'request_json', network)
    monkeypatch.setattr(ck, 'build_opener', network)
    monkeypatch.setattr('crawling.dacon.crawler.collect', network)
    for _ in range(3):
        result = api()
        assert result['status'] == 'partial'
        assert len(result['activities']) == 1 and len(result['activities'][0]['source_links']) == 2
        assert result['sources'][1]['status'] == 'success'
    network.assert_not_called()

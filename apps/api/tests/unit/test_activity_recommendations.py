from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from threading import Event
from unittest.mock import Mock

import pytest

from providers.external import contestkorea as provider
from services.activity_catalog import ActivityCatalog
from services.activity_recommendations import KST, capture_profile, eligible_target, period_status, recommend

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from experience_activity_regressions import BIKE_DATA, FRONTEND, postings

FIXTURE = json.loads((Path(__file__).resolve().parents[4] / 'data/reference/external-fixtures/activities/contestkorea-demo-v1.json').read_text())
NOW = datetime(2026, 11, 12, 12, tzinfo=KST)
SOURCES = [{'kind': k, 'status': 'success'} for k in provider.KINDS]
DATA = {'career_goal': '데이터 분석가', 'target_role': None}
MARKETING = {'career_goal': '마케팅 지망생', 'target_role': None}


def records():
    return [provider.normalize(row, 'extracurricular' if row['STR_MEETCODE'] == 'supporter' else 'competition') for row in FIXTURE['meetings']]


def test_incident_general_words_and_project_subject_do_not_qualify():
    assert recommend(FRONTEND, postings(), SOURCES, NOW)['activities'] == []
    ranked = recommend(BIKE_DATA, postings(), SOURCES, NOW)['activities']
    assert {item['title'] for item in ranked} == {'공공데이터 활용 경진대회', '자전거 수요 데이터 분석 경진대회'}
    for item in ranked:
        for evidence, reason in zip(item['evidence'], item['reasons'], strict=True):
            assert evidence['matched_term'] not in {'있는', '자전거'}
            assert evidence['matched_term'] in evidence['posting_quote']
            assert evidence['posting_quote'] == item[evidence['posting_field']]
            assert evidence['matched_term'] in reason and evidence['posting_quote'] in reason


@pytest.mark.parametrize('subject', ['자전거', '버스', '도서관', '환경'])
def test_subject_overlap_is_not_a_career_activity(subject):
    profile = {**BIKE_DATA, 'career_goal': f'{subject} 수요를 데이터로 분석하고 싶습니다.'}
    item = {**postings()[1], 'title': f'전국 {subject} 대행진', 'category': '체험'}
    assert recommend(profile, [item], SOURCES, NOW)['activities'] == []


@pytest.mark.parametrize('field,quote', [
    ('title', '자전거 수요 데이터 분석 경진대회'),
    ('category', '데이터 분석'),
    ('description_text', '참가자는 대여 이력 데이터로 수요를 분석하고 시각화 결과를 제출합니다.'),
])
def test_available_career_evidence_in_each_posting_field_can_qualify(field, quote):
    item = {**postings()[1], field: quote}
    ranked = recommend(BIKE_DATA, [item], SOURCES, NOW)['activities']
    assert len(ranked) == 1
    assert all(e['posting_field'] == field and e['posting_quote'] == quote for e in ranked[0]['evidence'])
    assert all(quote in reason for reason in ranked[0]['reasons'])


def test_body_is_optional_and_unrelated_body_does_not_supply_missing_evidence():
    item = {**postings()[1], 'description_text': '누구나 참여할 수 있는 시민 행사입니다.'}
    assert recommend(BIKE_DATA, [item], SOURCES, NOW)['activities'] == []
    assert recommend(BIKE_DATA, [{**item, 'description_text': None}], SOURCES, NOW)['activities'] == []


def test_every_scored_topic_has_its_own_displayed_source():
    profile = {'career_goal': '데이터 분석과 마케팅을 하고 싶습니다.', 'target_role': None}
    item = {**postings()[2], 'title': '데이터 분석과 마케팅 경진대회'}
    result, = recommend(profile, [item], SOURCES, NOW)['activities']
    assert len(result['reasons']) == len(result['evidence']) == 2
    assert result['score'] == 20
    assert all(e['matched_term'] in reason for e, reason in zip(result['evidence'], result['reasons']))


@pytest.mark.parametrize('profile,title', [
    (FRONTEND, 'React 웹 접근성 실습 캠프'),
    ({'career_goal': '사용성 테스트를 배우고 싶습니다.'}, 'Figma 프로토타입 워크숍'),
    ({'career_goal': '공공 자전거 수요를 분석하고 싶습니다.'}, '공공데이터 활용 경진대회'),
    ({'career_goal': '환경 분야 전문가', 'target_role': '환경 연구원'}, '환경 문제 해결 공모전'),
])
def test_specific_capability_and_goal_only_matches_remain(profile, title):
    item = {**postings()[1], 'title': title, 'category': '교육'}
    assert len(recommend(profile, [item], SOURCES, NOW)['activities']) == 1


def test_order_and_grounded_reasons_change_with_goal():
    data = recommend(DATA, records(), SOURCES, NOW)['activities']
    marketing = recommend(MARKETING, records(), SOURCES, NOW)['activities']
    assert [r['id'] for r in data] == ['data', 'both']
    assert [r['id'] for r in marketing] == ['marketing', 'both', 'supporter']
    for profile, ranked in ((DATA, data), (MARKETING, marketing)):
        assert all(profile['career_goal'] in item['reasons'][0] for item in ranked)
        for item in ranked:
            assert item['title'] in item['reasons'][0]
            assert 'Python' not in ' '.join(item['reasons'])
            for evidence in item['evidence']:
                assert evidence['posting_quote'] == item[evidence['posting_field']]


@pytest.mark.parametrize('period,now,status,deadline', [
    ('2026.11.01 ~ 2026.11.12', datetime(2026,11,12,23,59,59,tzinfo=KST), 'open', '2026-11-12'),
    ('2026.11.01 ~ 2026.11.12', datetime(2026,11,12,15,0,tzinfo=timezone.utc), 'closed', '2026-11-12'),
    ('2026.12.20 ~ 01.05', datetime(2027,1,1,tzinfo=KST), 'open', '2027-01-05'),
    ('12.20 ~ 2027.01.05', datetime(2026,12,25,tzinfo=KST), 'open', '2027-01-05'),
    ('2026-12-20 ~ 2027-01-05', NOW, 'upcoming', '2027-01-05'),
    ('2026.11.01 ~ 2026.11.12 18:00', datetime(2026,11,12,18,1,tzinfo=KST), 'closed', '2026-11-12'),
    ('2026년 11월 1일 ~ 2026년 11월 12일 18시', NOW, 'open', '2026-11-12'),
    ('상시 접수', NOW, 'open', None),
    ('11.01 ~ 11.30', NOW, 'unknown', None),
    ('2026.02.30 ~ 2026.12.01', NOW, 'unknown', None),
    ('2027.01.01 ~ 2026.12.01', NOW, 'unknown', None),
    ('상시 접수 종료', NOW, 'unknown', None),
    ('선착순 마감', NOW, 'unknown', None),
    ('2026.11.30', NOW, 'unknown', None),
    ('2026.11.01 ~ 2026.11.30 (조기마감 가능)', NOW, 'unknown', None),
])
def test_period_boundaries(period, now, status, deadline):
    result = period_status(period, now.astimezone(KST))
    assert result['status'] == status
    assert result.get('deadline') == deadline


@pytest.mark.parametrize('target,allowed', [
    ('대학생', True), ('누구나', True), ('고등학생, 대학생, 대학원생, 일반인', True),
    ('고등학생', False), ('대학원생', False), ('일반인', False), ('미정', False),
    ('대학생, 해당자 ▶', False), ('누구나 (대학생 제외)', False), ('서울 거주 대학생', False),
    ('대학생 3학년 이상', False), ('대학생/일반인', True), ('', False),
])
def test_conservative_eligibility(target, allowed):
    assert eligible_target(target) is allowed


def test_closed_ineligible_unknown_duplicate_and_unrelated_not_padded():
    original = records()[0]
    items = [original, original, {**original, 'id': 'closed', 'period': '2026.10.01 ~ 2026.10.31'},
             {**original, 'id': 'child', 'target': '초등학생'}, {**original, 'id': 'unknown', 'period': '협의'},
             {**original, 'id': 'unclear', 'target': '대학생, 해당자 ▶'}, records()[1]]
    assert [r['id'] for r in recommend(DATA, items, SOURCES, NOW)['activities']] == ['data']
    assert recommend({'career_goal': '천문학 연구원'}, items, SOURCES, NOW)['activities'] == []


def test_only_explicit_posting_skill_can_supplement_goal_reason():
    profile = {**DATA, 'confirmed_skills': ['Python', '데이터'], 'gap_skills': ['SQL', '통계']}
    item = recommend(profile, records(), SOURCES, NOW)['activities'][0]
    reasons = ' '.join(item['reasons'])
    assert '확인한 프로젝트 경험 “데이터”' in reasons
    assert '보완 후보 “통계”' in reasons
    assert 'Python' not in reasons and 'SQL' not in reasons


def test_generic_development_does_not_mean_software():
    item = {**records()[0], 'title': '상설공연 창작 콘텐츠 개발 아이디어 대회', 'category': '아이디어·건축·창업'}
    assert recommend({'career_goal': '백엔드 개발자'}, [item], SOURCES, NOW)['activities'] == []


def test_profile_uses_confirmed_experience_without_job_analysis(monkeypatch):
    monkeypatch.setattr('services.activity_recommendations.current_comparison', lambda *args: {
        'project_analysis': {'document_basis': 'current', 'experiences': [
            {'skill_name': '데이터', 'user_answer': {'status': 'confirmed'}},
            {'skill_name': 'Python', 'contribution_scope': 'personal', 'user_answer': None},
            {'skill_name': 'SQL', 'user_answer': {'status': 'no_experience'}},
        ]}, 'comparisons': []})
    profile, _ = capture_profile(None, {**DATA, 'input_revision': 1})
    assert profile['confirmed_skills'] == ['데이터']
    assert profile['gap_skills'] == []


def test_real_adapter_contract_auth_params_dedupe_and_partial(monkeypatch):
    calls = []
    def request(endpoint, params, key):
        calls.append((endpoint, params, key))
        if endpoint == 'menu_info_api.php':
            return [{'resultcode': '1', 'resultmsg': '성공', 'Data': FIXTURE['menus']}]
        if params['Txt_bcode'] == '0302':
            raise provider.ProviderError('provider_unavailable')
        return [{'resultcode': '1', 'resultmsg': '성공', 'Data': FIXTURE['meetings'] + FIXTURE['meetings'][:1]}]
    monkeypatch.setattr(provider, 'request_json', request)
    result = provider.collect_kind('competition', 'test-secret')
    assert result.status == 'partial' and len(result.items) == 4
    assert result.failed_categories == 1
    assert calls[0] == ('menu_info_api.php', {'int_gbn': '1'}, 'test-secret')
    assert {c[1]['Txt_bcode'] for c in calls[1:]} == {'0301', '0302'}
    calls.clear()
    provider.collect_kind('extracurricular', 'test-secret')
    assert calls[0][1] == {'int_gbn': '2'}


@pytest.mark.parametrize('payload', [[{'resultcode': '-1', 'resultmsg': 'secret'}], {}, [{'unexpected': 'value'}]])
def test_invalid_menu_or_api_error_never_becomes_success(monkeypatch, payload):
    monkeypatch.setattr(provider, 'request_json', lambda *args: payload)
    result = provider.collect_kind('competition', 'test-secret')
    assert result.status == 'error' and not result.items
    assert 'secret' not in str(result)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://user:pass@example.com/',
    'https://www.contestkorea.com/api/meeting_info_api.php?apikey=secret',
    'https://example.com/?apikey=secret'])
def test_unsafe_original_links_rejected(url):
    with pytest.raises(ValueError):
        provider.normalize({**FIXTURE['meetings'][0], 'STR_URL': url}, 'competition')


def test_transport_no_redirect_and_no_secret_errors(monkeypatch, caplog):
    def opener(handler):
        assert handler is provider.NoRedirect
        client = Mock()
        def open_request(request, timeout):
            from urllib.parse import parse_qs, urlsplit
            assert parse_qs(urlsplit(request.full_url).query) == {'int_gbn': ['1'], 'apikey': ['test-secret']}
            raise OSError(request.full_url)
        client.open.side_effect = open_request
        return client
    monkeypatch.setattr(provider, 'build_opener', opener)
    with pytest.raises(provider.ProviderError) as error:
        provider.request_json('menu_info_api.php', {'int_gbn': '1'}, 'test-secret')
    assert str(error.value) == 'provider_unavailable'
    assert 'test-secret' not in caplog.text
    assert error.value.__suppress_context__


def test_missing_key_and_empty_catalog_are_distinct(monkeypatch):
    assert provider.collect_kind('competition', '').error_code == 'not_configured'
    monkeypatch.setattr(provider, 'request_json', lambda endpoint, *args: FIXTURE['menus'] if endpoint == 'menu_info_api.php' else [])
    assert provider.collect_kind('competition', 'test-secret').status == 'success'
    assert recommend(DATA, [], SOURCES, NOW)['status'] == 'success'
    assert recommend(DATA, [], [{'status': 'error'}, {'status': 'error'}], NOW)['status'] == 'error'


def test_cache_reuse_partial_failures_and_deadline_recheck(monkeypatch):
    monkeypatch.setenv('CONTESTKOREA_API_KEY', 'test-secret')
    tick = [0]
    fetch = Mock(side_effect=lambda kind, key: provider.Collection(tuple(records()[:1]), 'success') if kind == 'competition' else provider.Collection((), 'error'))
    catalog = ActivityCatalog(fetch, lambda: tick[0])
    items, sources = catalog.get()
    assert len(items) == 1 and fetch.call_count == 2
    assert recommend(DATA, items, sources, NOW)['status'] == 'partial'
    assert len(recommend(DATA, items, sources, NOW)['activities']) == 1
    items, sources = catalog.get()
    assert fetch.call_count == 2 and all(s['cache_hit'] for s in sources)
    assert recommend(DATA, items, sources, datetime(2026,12,1,tzinfo=KST))['activities'] == []
    tick[0] = 121
    catalog.get()
    assert fetch.call_count == 3  # Only the failed kind retries.
    tick[0] = 1801
    catalog.get()
    assert fetch.call_count == 5
    monkeypatch.setenv('CONTESTKOREA_API_KEY', 'changed-secret')
    catalog.get()
    assert fetch.call_count == 7


def test_concurrent_refresh_is_single_flight_and_no_expired_fallback():
    entered, release = Event(), Event()
    tick = [0]
    def fetch(*args):
        entered.set(); assert release.wait(2)
        return provider.Collection(tuple(records()), 'success')
    fetch = Mock(side_effect=fetch)
    catalog = ActivityCatalog(fetch, lambda: tick[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(catalog.get_kind, 'competition', 'key')
        assert entered.wait(2)
        b = pool.submit(catalog.get_kind, 'competition', 'key')
        release.set()
        assert a.result()[0] == b.result()[0]
    assert fetch.call_count == 1
    tick[0] = 1801
    fetch.side_effect = None
    fetch.return_value = provider.Collection((), 'error')
    assert catalog.get_kind('competition', 'key')[0] == ()


def test_live_envelope_and_promoted_kind_and_literal_title():
    raw = {**FIXTURE['meetings'][0], 'STR_MEETCODE': '202611070021',
           'STR_MEETING': '<AI 챌린지> 데이터 분석', 'STR_DATE1': '11.07~11.16',
           'STR_URL': 'https://www.contestkorea.com/sub/view.php?Txt_gbn=1&str_no=202611070021'}
    record = provider.normalize(provider.rows([{'resultcode': '1', 'Data': [raw]}])[0], 'extracurricular')
    assert record['kind'] == 'competition'
    assert record['title'] == '<AI 챌린지> 데이터 분석'
    assert recommend(DATA, [record], SOURCES, NOW)['activities'] == []  # Never infer the year from its ID.


@pytest.mark.parametrize('page_period,verified', [('2026.11.07 ~ 2026.11.16', True),
    ('2025.11.07 ~ 2025.11.16', True), ('2026.11.07 ~ 2026.11.17', False), ('11.07 ~ 11.16', False)])
def test_years_require_same_posting_original_table(monkeypatch, page_period, verified):
    record = {**records()[0], 'id': '202611070021', 'period': '11.07~11.16',
              'url': 'https://www.contestkorea.com/sub/view.php?str_no=202611070021'}
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=Mock(read=lambda *args: f'<table><tr><th>접수기간</th><td>{page_period}</td></tr></table>'.encode()))
    opener.open.return_value.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(provider, 'build_opener', lambda *args: opener)
    enriched = provider.verify_period(record)
    assert ('verified_period' in enriched) is verified
    assert enriched['period'] == record['period']
    expected = verified and page_period.startswith('2026')
    assert bool(recommend(DATA, [enriched], SOURCES, NOW)['activities']) is expected


def test_detail_failure_or_mismatched_link_cannot_invent_year(monkeypatch):
    opener = Mock(); opener.open.side_effect = OSError('unavailable')
    monkeypatch.setattr(provider, 'build_opener', lambda *args: opener)
    item = {**records()[0], 'period': '11.01~11.30'}
    assert provider.verify_period(item)['period_source'] == 'unverified'
    assert provider.verify_period({**item, 'id': 'other'})['period_source'] == 'unverified'


def test_provider_cannot_echo_key_into_records(monkeypatch):
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=Mock(read=lambda *args: b'[{"STR_MEETING":"test-secret"}]'))
    opener.open.return_value.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(provider, 'build_opener', lambda *args: opener)
    with pytest.raises(provider.ProviderError, match='provider_unavailable'):
        provider.request_json('meeting_info_api.php', {'Txt_bcode': '0301'}, 'test-secret')

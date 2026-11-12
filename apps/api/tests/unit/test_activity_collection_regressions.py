"""Regression examples from the cd72f43 review (no live network)."""
from unittest.mock import MagicMock

import pytest

from test_contestkorea_collection import NOW, record
from providers.external import contestkorea as ck
from services.activity_recommendations import recommend


@pytest.mark.parametrize('label', ['접수기간', '접수 기간', '접수\n기간', '신청 기간', '모집기간'])
def test_registration_label_variants(monkeypatch, label):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        f'<table><tr><th>{label}</th><td>2026.11.01 ~ 2026.11.30</td></tr></table>').encode()
    opener = MagicMock(); opener.open.return_value = response
    monkeypatch.setattr(ck, 'build_opener', lambda *args: opener)
    result = ck.verify_period(record(period='11.01~11.30'))
    assert result.get('verified_period') == '2026.11.01 ~ 2026.11.30'


def test_cross_source_duplicates_before_top_twelve():
    items = [record(id=str(i), title=f'데이터 분석 대회 {i}',
                    official_application_url=f'https://apply.example/events/{i}') for i in range(13)]
    duplicate = {**items[0], 'source': 'daker', 'id': '00', 'original_id': 'other',
                 'url': 'https://daker.ai/public/hackathons/other', 'source_label': '데이커',
                 'application_start_at': '2026-11-01T00:00:00+09:00',
                 'application_end_at': '2026-11-30T23:59:59.999999+09:00'}
    result = recommend({'career_goal': '데이터 분석가'}, [*items, duplicate], [{'status':'success'}], NOW)
    cards = result['activities']
    assert len(cards) == 12
    assert len({c['title'] for c in cards}) == 12
    merged, = [c for c in cards if c['title'] == items[0]['title']]
    assert {s['source'] for s in merged['source_links']} == {'contestkorea', 'daker'}
    assert len({s['url'] for s in merged['source_links']}) == 2


@pytest.mark.parametrize('label', ['대회기간', '개최 기간', '제출기간', '심사기간'])
def test_other_periods_never_substitute_registration(label):
    with pytest.raises(ValueError):
        ck.parse_detail(record(), f'<table><tr><th>{label}</th><td>2026.11.01 ~ 2026.11.30</td></tr></table>'.encode())


def test_unknown_and_closed_and_cancelled_are_not_parser_failures():
    for text, field in [('미정', 'unknown'), ('접수 조기 마감', 'application_closed'), ('대회 취소', 'application_cancelled')]:
        result = ck.parse_detail(record(), f'<table><tr><th>접수 기간</th><td>{text}</td></tr></table>'.encode())
        assert result.get('period_source') == field or result.get(field) is True
        assert not result.get('verification_error')


def test_official_application_url_is_not_publisher_or_homepage():
    result = ck.parse_detail(record(), b'''<table><tr><th>\xec\xa0\x91\xec\x88\x98\xea\xb8\xb0\xea\xb0\x84</th>
      <td>2026.11.01 ~ 2026.11.30</td></tr></table>''')
    assert 'official_application_url' not in result
    page = '<table><tr><th>접수 기간</th><td>2026.11.01 ~ 2026.11.30</td></tr><tr><th>홈페이지</th><td><a href="https://host.test">주최사</a></td></tr><tr><th>접수하기</th><td><a href="https://apply.test/event/1?utm_source=ck">신청</a></td></tr></table>'
    result = ck.parse_detail(record(), page.encode())
    assert result['url'] == record()['url']
    assert result['official_application_url'] == 'https://apply.test/event/1'


def test_strict_identity_and_separate_editions():
    from services.activity_identity import merge_events
    a = {**record(), 'opens_at': '2026-11-01', 'closes_at': '2026-11-30'}
    b = {**a, 'id': 'another', 'source': 'daker', 'url': 'https://daker.ai/public/hackathons/a'}
    assert len(merge_events([a, b])) == 1
    for change in ({'host': '다른 기관'}, {'title': '데이터 분석 공모전 2회'}, {'closes_at': '2026-12-30'}, {'host': ''}):
        assert len(merge_events([a, {**b, **change}])) == 2
    a['official_application_url'] = b['official_application_url'] = 'https://apply.test/events/1'
    assert len(merge_events([a, {**b, 'title': '다른 사이트의 데이터 대회 제목'}])) == 1
    assert len(merge_events([a, {**b, 'opens_at': '2026-12-01', 'closes_at': '2026-12-31'}])) == 2
    assert len(merge_events([a, {**b, 'official_application_url': 'https://apply.test/events/2'}])) == 2


def test_same_numeric_id_in_different_sources_is_not_dropped():
    a = record(id='123', title='데이터 분석 대회 A')
    b = {**a, 'source': 'other', 'title': '데이터 분석 대회 B'}
    assert len(recommend({'career_goal':'데이터 분석가'}, [a,b], [{'status':'success'}], NOW)['activities']) == 2


def test_ck_official_limit_option_and_repeated_response_termination(monkeypatch):
    calls = []
    raw = {'STR_MEETCODE': '1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
           'STR_DATE1':'11.01~11.30','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    def request(endpoint, params, key):
        calls.append((endpoint, params))
        return [{'STR_BCODE':'0301'}] if endpoint == 'menu_info_api.php' else [raw] * params['limitsu']
    monkeypatch.setattr(ck, 'request_json', request)
    monkeypatch.setattr(ck, 'verify_period', lambda item: {**item, 'verified_period':record()['period']})
    result = ck.collect_kind('competition', 'secret', eligible_only=True, now=NOW)
    assert [p['limitsu'] for e,p in calls if e=='meeting_info_api.php'] == [100,200]
    assert result.limited_categories == 1 and len(result.items) == 1


class ListingPage:
    def __init__(self, pages):
        from unittest.mock import Mock
        self.pages, self.index = pages, 0
        self.more = MagicMock()
        self.more.count.return_value = 1
        self.more.first.is_visible.side_effect = lambda: self.index < len(self.pages)-1
        self.more.first.is_enabled.return_value = True
        self.more.first.click.side_effect = self.advance
        self.more.filter.return_value = self.more
        self.pending = MagicMock()
        self.pending.__enter__.return_value.value.status = 200
        self.pending.__enter__.return_value.value.finished.return_value = None
    def advance(self):
        self.index += 1
    def evaluate(self, script):
        return self.pages[self.index]
    def locator(self, selector):
        assert selector == 'button.bgBtn'
        return self.more
    def expect_response(self, *args, **kwargs):
        return self.pending
    def wait_for_function(self, *args, **kwargs):
        pass


def card(id):
    return {'href':f'https://dacon.io/competitions/official/{id}/overview/', 'title':f'AI 대회 {id}', 'status':'진행중'}


@pytest.mark.parametrize('pages', [[[card('1')],[card('1'),card('2')],[card('1'),card('2')]],
                                  [[card('1')],[card('2')],[]]])
def test_dacon_second_page_repeat_stop_one_detail_per_id(monkeypatch,pages):
    from crawling.dacon import crawler
    from crawling.dacon.validation import validate_records
    page = ListingPage(pages)
    cards = crawler.listing_cards(page)
    items = crawler.merge_cards([(c,'list') for c in cards])
    read = MagicMock(side_effect=lambda page,item:item)
    monkeypatch.setattr(crawler,'read_dacon',read)
    monkeypatch.setattr(crawler.time,'sleep',lambda seconds:None)
    result = validate_records(crawler.crawl_details(page,items))
    assert {r['original_id'] for r in result} == {'1','2'}
    assert read.call_count == 2 and page.index == 2


def test_dacon_pagination_failure_keeps_already_discovered_cards():
    from crawling.dacon.crawler import ListingFailure,listing_cards
    page=ListingPage([[card('1')],[card('2')]])
    page.pending.__enter__.return_value.value.status=503
    with pytest.raises(ListingFailure) as error:
        listing_cards(page)
    assert [c['href'] for c in error.value.cards] == [card('1')['href']]


@pytest.mark.parametrize('value,expected', [('마감','application_closed'),('취소','application_cancelled')])
def test_explicit_status_cell_overrides_open_dates(value,expected):
    page=f'<table><tr><th>접수기간</th><td>2026.11.01 ~ 2026.11.30</td></tr><tr><th>접수 상태</th><td>{value}</td></tr></table>'
    assert ck.parse_detail(record(),page.encode())[expected]


def test_ck_broken_structure_is_partial_zero_not_success_zero(monkeypatch):
    raw={'STR_MEETCODE':'1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
         'STR_DATE1':'11.01~11.30','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    monkeypatch.setattr(ck,'request_json',lambda endpoint,*args: [{'STR_BCODE':'0301'}] if endpoint=='menu_info_api.php' else [raw])
    opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=b'<html>changed structure</html>'
    monkeypatch.setattr(ck,'build_opener',lambda *args:opener)
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW)
    assert result.status=='partial' and not result.items
    assert result.parse_failures==1 and result.network_failures==0 and result.fetched_items==1
    assert result.observations[0]['verification_error']=='parse_error'
    opener.open.side_effect=OSError('temporary outage')
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW)
    assert result.network_failures==1 and result.parse_failures==0


def test_ck_original_unknown_period_can_be_success_zero(monkeypatch):
    raw={'STR_MEETCODE':'1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
         'STR_DATE1':'미정','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    monkeypatch.setattr(ck,'request_json',lambda endpoint,*args: [{'STR_BCODE':'0301'}] if endpoint=='menu_info_api.php' else [raw])
    opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value='<table><tr><th>접수 기간</th><td>미정</td></tr></table>'.encode()
    monkeypatch.setattr(ck,'build_opener',lambda *args:opener)
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW)
    assert result.status=='success' and result.unknown_periods==1 and not result.items
    assert result.parse_failures==result.network_failures==0


def test_registration_date_variants_and_extension_use_detail():
    page='<table><tr><th>참가 신청 기간</th><td>2026년 11월 1일 09:00 ~ 2026-12-01 18:00</td></tr></table>'
    item=ck.parse_detail(record(period='11.01~11.30'),page.encode())
    from services.activity_eligibility import period_status
    assert period_status(item['verified_period'],NOW)['closes_at']=='2026-12-01T18:00:00+09:00'


def test_distinct_editions_with_shared_application_url_stay_separate():
    from services.activity_identity import merge_events
    a={**record(title='제1회 AI 대회'),'opens_at':None,'closes_at':None,'official_application_url':'https://apply.test/annual'}
    b={**a,'source':'daker','id':'b','title':'제2회 AI 대회'}
    assert len(merge_events([a,b]))==2


def test_expansion_failure_keeps_previously_returned_records(monkeypatch):
    raw={'STR_MEETCODE':'1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
         'STR_DATE1':'11.01~11.30','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    def request(endpoint,params,key):
        if endpoint=='menu_info_api.php':return [{'STR_BCODE':'0301'}]
        if params['limitsu']==100:return [raw]*100
        raise ck.ProviderError('provider_unavailable')
    monkeypatch.setattr(ck,'request_json',request)
    monkeypatch.setattr(ck,'verify_period',lambda item:{**item,'verified_period':record()['period']})
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW)
    assert result.status=='error' and result.network_failures==1
    assert len(result.items)==1 and result.items[0]['id']=='1'


def test_unchanged_expired_historical_detail_is_not_fetched_again(monkeypatch):
    raw={'STR_MEETCODE':'1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
         'STR_DATE1':'10.01~10.31','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    old={**ck.normalize(raw,'competition'),'verified_period':'2026.10.01 ~ 2026.10.31'}
    old.pop('listing_signature')  # Historical snapshots predate this field.
    monkeypatch.setattr(ck,'request_json',lambda endpoint,*args: [{'STR_BCODE':'0301'}] if endpoint=='menu_info_api.php' else [raw])
    verify=MagicMock(side_effect=AssertionError('no expired historical detail HTTP'))
    monkeypatch.setattr(ck,'verify_period',verify)
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW,known_details={'1':old})
    assert result.status=='success' and result.reused_details==1 and not result.items
    verify.assert_not_called()
    raw['STR_DATE1']='11.01~11.30'
    verify.side_effect=lambda item:{**item,'verified_period':record()['period']}
    result=ck.collect_kind('competition','secret',eligible_only=True,now=NOW,known_details={'1':old})
    assert len(result.items)==1 and verify.call_count==1


def test_official_application_identity_tolerates_publisher_date_precision():
    from services.activity_identity import merge_events
    a={**record(),'opens_at':'2026-11-01T00:00:00+09:00','closes_at':'2026-11-30T23:59:59.999999+09:00',
       'official_application_url':'https://apply.test/event'}
    b={**a,'id':'b','source':'daker','opens_at':'2026-11-01T09:00:00+09:00','closes_at':'2026-11-30T10:00:00+09:00'}
    assert len(merge_events([a,b]))==1
    a.pop('official_application_url');b.pop('official_application_url')
    assert len(merge_events([a,b]))==2

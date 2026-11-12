from datetime import datetime
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from services.activity_eligibility import KST
from services.activity_recommendations import recommend
from crawling.contestkorea.collector import compact_records, collect, CollectionIncomplete
from providers.external import contestkorea as provider

NOW = datetime(2026,11,12,9,10,tzinfo=KST)


def record(**changes):
    return {'id': '202611010001', 'kind': 'competition', 'source': 'contestkorea',
            'source_label': '콘테스트코리아', 'title': '데이터 분석 공모전', 'category': '데이터', 'host': '주최기관',
            'target': '대학생', 'period': '2026.11.01 ~ 2026.11.30',
            'url': 'https://www.contestkorea.com/sub/view.php?str_no=202611010001', **changes}


@pytest.mark.parametrize('period,target,expected', [
    ('2026.11.01 ~ 2026.11.30', '대학생', True),
    ('2026.12.01 ~ 2026.12.31', '누구나', True),
    ('상시 접수', '고등학생, 대학생, 일반인', True),
    ('2026.11.01 ~ 2026.11.12 09:09', '누구나', False),
    ('2026.10.01 ~ 2026.10.31', '대학생', False),
    ('11.01~11.30', '대학생', False),
    ('미정', '대학생', False),
    ('상시 접수 종료', '누구나', False),
    ('상시 접수', '대학원생', False),
    ('상시 접수', '고등학생', False),
    ('상시 접수', '누구나 (대학생 제외)', False),
    ('상시 접수', '대학생, 해당자 ▶', False),
])
def test_only_open_upcoming_and_verified_undergraduate_records(period, target, expected):
    assert bool(compact_records([record(period=period, target=target)], NOW)) is expected


def test_upcoming_is_recommended_and_switches_to_open_at_start():
    rows = compact_records([record(period='2026.11.13 09:00 ~ 2026.11.30')], NOW)
    profile, sources = {'career_goal': '데이터 분석가'}, [{'status': 'success'}]
    result = recommend(profile, rows, sources, datetime(2026,11,13,8,59,tzinfo=KST))
    assert len(rows) == 1 and result['activities'][0]['status'] == 'upcoming'
    assert result['activities'][0]['opens_at'] == '2026-11-13T09:00:00+09:00'
    assert result['valid_until'] == '2026-11-13T09:00:00+09:00'
    assert recommend(profile, rows, sources, datetime(2026,11,13,9,0,tzinfo=KST))['activities'][0]['status'] == 'open'


def test_minimal_fields_no_html_images_raw_response_or_daily_derived_fields():
    result, = compact_records([record(raw_response='x'*100000, html='<html>large</html>',
                                      poster='image', fetched_at=NOW.isoformat(), status='open')], NOW)
    assert set(result) == {'id','kind','title','category','host','target','period','url'}
    assert len(compact_records([record(), record()], NOW)) == 1
    with pytest.raises(ValueError):
        compact_records([record(), record(title='different')], NOW)


def test_filter_before_detail_avoids_unneeded_requests(monkeypatch):
    def raw(id, target, period):
        return {'STR_MEETCODE': id, 'STR_MEETING': 'AI 대회', 'STR_MENU':'AI', 'STR_HOST':'기관',
                'STR_TARGET':target, 'STR_DATE1':period, 'STR_URL':f'https://www.contestkorea.com/sub/view.php?str_no={id}'}
    records = [raw('1','고등학생','11.01~11.30'), raw('2','대학생','2026.10.01 ~ 2026.10.31'),
               raw('3','대학생','11.01~11.30')]
    monkeypatch.setattr(provider, 'request_json', lambda endpoint,*args: [{'STR_BCODE':'0301'}] if endpoint=='menu_info_api.php' else records)
    verify = Mock(side_effect=lambda item: {**item, 'verified_period':'2026.11.01 ~ 2026.11.30'})
    monkeypatch.setattr(provider, 'verify_period', verify)
    result = provider.collect_kind('competition', 'secret', eligible_only=True, now=NOW)
    assert result.status == 'success' and [r['id'] for r in result.items] == ['3']
    assert verify.call_count == 1


def test_unknown_period_skipped_but_detail_transport_failure_is_failure(monkeypatch):
    raw = {'STR_MEETCODE':'1','STR_MEETING':'AI','STR_MENU':'AI','STR_HOST':'기관','STR_TARGET':'대학생',
           'STR_DATE1':'11.01~11.30','STR_URL':'https://www.contestkorea.com/sub/view.php?str_no=1'}
    monkeypatch.setattr(provider, 'request_json', lambda endpoint,*args: [{'STR_BCODE':'0301'}] if endpoint=='menu_info_api.php' else [raw])
    monkeypatch.setattr(provider, 'verify_period', lambda item: {**item,'period_source':'unverified'})
    result = provider.collect_kind('competition', 'secret', eligible_only=True, now=NOW)
    assert result.status == 'success' and result.items == ()
    monkeypatch.setattr(provider, 'verify_period', lambda item: {**item,'period_source':'unverified','verification_error':'provider_unavailable'})
    result = provider.collect_kind('competition', 'secret', eligible_only=True, now=NOW)
    assert result.status == 'partial' and result.failed_details == 1


def test_either_kind_failure_aborts_publication(monkeypatch):
    monkeypatch.setattr('crawling.contestkorea.collector.collect_kind', Mock(side_effect=[
        provider.Collection((record(),), 'success'), provider.Collection((), 'partial', failed_categories=1)]))
    with pytest.raises(CollectionIncomplete):
        collect()


def test_daily_runner_continues_other_source_after_failure(monkeypatch, capsys):
    from crawling.activities import run
    execute = Mock(side_effect=[{'status':'failed'}, {'status':'success'}])
    monkeypatch.setattr(run, 'run_source', execute)
    monkeypatch.setattr(sys, 'argv', ['run', '--mode', 'scheduled'])
    assert run.main() == 1
    assert [call.args[:2] for call in execute.call_args_list] == [('contestkorea','scheduled'), ('dacon','scheduled')]
    assert len(capsys.readouterr().out.splitlines()) == 2

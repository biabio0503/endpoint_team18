from datetime import datetime
from unittest.mock import Mock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import pytest

from providers.external import contestkorea as ck
from services.activity_eligibility import KST, contestkorea_in_scope

NOW = datetime(2026, 11, 12, 12, tzinfo=KST)
MENUS = {
    kind: [{'STR_BCODE': code, 'STR_IDXWORD': name} for code, name in categories.items()]
    for kind, categories in ck.CONTESTKOREA_CATEGORIES.items()
}


def listing(id, category, *, kind='1', period='2026.11.01 ~ 2026.11.30'):
    return {'STR_MEETCODE': id, 'STR_MEETING': '데이터 분석 대회 ' + id,
            'STR_MENU': category, 'STR_HOST': '기관', 'STR_TARGET': '대학생', 'STR_DATE1': period,
            'STR_URL': f'https://www.contestkorea.com/sub/view.php?Txt_gbn={kind}&str_no={id}'}


def test_requests_only_allowed_codes_and_filters_promotions_before_detail(monkeypatch):
    calls = []
    sci = listing('sci', '학문 · 과학 • IT')
    multi = listing('multi', '스포츠, 아이디어 • 건축 · 창업')
    promoted = listing('other', '교육 • 강연 • 멘토링 • 세미나', kind='1')
    education = listing('edu', '교육 • 강연 • 멘토링 • 세미나', kind='2')
    exhibition = listing('expo', '전시 • 박람 • 행사 • 축제', kind='2')
    closed = listing('closed', '학문•과학•IT', period='2026.10.01 ~ 2026.10.31')
    unknown = listing('unknown', '학문•과학•IT', period='10.01 ~ 10.31')
    cross = listing('cross', '기획 • 홍보 • 마케팅', kind='2')
    def request(endpoint, params, key):
        calls.append((endpoint, dict(params)))
        if endpoint == 'menu_info_api.php':
            kind = 'competition' if params['int_gbn'] == '1' else 'extracurricular'
            return MENUS[kind] + [{'STR_BCODE': '030110001', 'STR_IDXWORD': '문학•문예'}]
        if params['Txt_bcode'].startswith('03'):
            return [sci, multi, promoted, cross, closed, unknown, education]
        return [education, exhibition, sci, cross]
    verify = Mock(side_effect=lambda item: {**item, 'verified_period': '2026.11.01 ~ 2026.11.30'})
    monkeypatch.setattr(ck, 'request_json', request)
    monkeypatch.setattr(ck, 'verify_period', verify)
    cache = {}
    a = ck.collect_kind('competition', 'key', eligible_only=True, now=NOW, detail_cache=cache)
    b = ck.collect_kind('extracurricular', 'key', eligible_only=True, now=NOW, detail_cache=cache)
    assert a.status == b.status == 'success'
    assert {p['Txt_bcode'] for e, p in calls if e == 'meeting_info_api.php'} == {
        '030310001', '031410001', '040410001', '040510001'}
    assert {call.args[0]['id'] for call in verify.call_args_list} == {'sci', 'multi', 'edu', 'expo', 'unknown'}
    assert verify.call_count == 5
    assert a.skipped_closed == 1 and a.detail_requests + b.detail_requests == 5
    assert a.fetched_items == 14 and b.fetched_items == 8
    assert {item['id'] for item in a.items + b.items} == {'sci', 'multi', 'edu', 'expo', 'unknown'}


def test_missing_menu_is_partial_and_never_fetches_other_codes(monkeypatch):
    calls = []
    def request(endpoint, params, key):
        if endpoint == 'menu_info_api.php':
            return [MENUS['competition'][0], {'STR_BCODE': '030110001', 'STR_IDXWORD': '문학•문예'}]
        calls.append(params['Txt_bcode'])
        return [listing('1', '학문•과학•IT')]
    monkeypatch.setattr(ck, 'request_json', request)
    monkeypatch.setattr(ck, 'verify_period', lambda r: {**r, 'verified_period': r['period']})
    result = ck.collect_kind('competition', 'key', eligible_only=True, now=NOW)
    assert result.status == 'partial' and result.missing_categories == ('031410001',)
    assert calls == ['030310001'] and len(result.items) == 1
    monkeypatch.setattr(ck, 'request_json', lambda *args: [])
    result = ck.collect_kind('competition', 'key', now=NOW)
    assert result.status == 'error' and len(result.missing_categories) == 2


@pytest.mark.parametrize('value,expected', [
    ('학문 · 과학 • IT', True), ('스포츠|아이디어•건축•창업', True),
    ('학문•과학•IT 관련 행사', False), ('IT', False), ('교육', False),
    ('교육•강연•멘토링•세미나', False), ('아이디어•건축•창업교육', False),
])
def test_only_whole_category_names_for_its_kind(value, expected):
    assert contestkorea_in_scope({'kind': 'competition', 'category': value}) is expected


def test_previous_extension_unknown_year_and_original_closure(monkeypatch):
    values = [listing('old', '학문•과학•IT', period='2026.10.01 ~ 2026.10.31'),
              listing('unknown', '학문•과학•IT', period='10.01 ~ 10.31'),
              listing('cancel', '학문•과학•IT')]
    def request(endpoint, params, key):
        return MENUS['competition'] if endpoint == 'menu_info_api.php' else values
    old = {**ck.normalize(values[0], 'competition'), 'verified_period': '2026.11.01 ~ 2026.11.30'}
    def detail(item):
        if item['id'] == 'cancel':
            return {**item, 'application_cancelled': True, 'period_source': 'original_page'}
        return {**item, 'verified_period': '2026.11.01 ~ 2026.11.30', 'period_source': 'original_page'}
    verify = Mock(side_effect=detail)
    monkeypatch.setattr(ck, 'request_json', request)
    monkeypatch.setattr(ck, 'verify_period', verify)
    result = ck.collect_kind('competition', 'key', eligible_only=True, now=NOW, known_details={'old': old})
    assert {i['id'] for i in result.items} == {'old', 'unknown'}
    assert verify.call_count == result.detail_requests == 3

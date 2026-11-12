"""Event-level decisions must not depend on publisher order or time synthesis."""
from datetime import datetime

import pytest

from test_contestkorea_collection import record, NOW
from crawling.dacon.validation import extract_evidence, validate_records
from test_dacon import record as daker_record
from services.activity_eligibility import application_period, KST
from services.activity_recommendations import recommend


@pytest.mark.parametrize('reverse', [False, True])
def test_top_twelve_after_identity_with_generic_peer(reverse):
    items = [record(id=str(i), title=f'데이터 분석 대회 {i}', official_application_url=f'https://apply.test/{i}')
             for i in range(13)]
    peer = {**items[0], 'source': 'partner', 'id': 'generic', 'title': '미래 챌린지', 'category': '',
            'url': 'https://partner.test/original'}
    rows = [*items, peer]
    result = recommend({'career_goal': '데이터 분석가'}, rows[::-1] if reverse else rows, [{'status': 'success'}], NOW)
    assert len(result['activities']) == 12
    card, = [i for i in result['activities'] if i['id'] == '0']
    assert len(card['source_links']) == 2
    assert card['evidence'][0]['source'] == 'contestkorea'


@pytest.mark.parametrize('original,precision', [('2026.11.01 ~ 2026.11.30', 'date'),
    ('2026.11.01 09:00 ~ 2026.11.30 10:00', 'time'),
    ('2026.11.01 ~ 2026.11.30 23:59', 'time')])
@pytest.mark.parametrize('historical', [False, True])
def test_precision_comes_from_original_text_even_for_historical_payload(original, precision, historical):
    item = daker_record(**extract_evidence('[참가 자격]\n누구나\n[일정]\n참가 신청 기간\n' + original))
    if historical:
        item.pop('application_end_precision')
    item, = validate_records([item])
    period = application_period(item, NOW)
    assert period['deadline_precision'] == precision
    assert ('당일 포함' in period['deadline_label']) == (precision == 'date')


def test_fallback_identity_does_not_treat_different_precision_as_same_period():
    a = record()
    b, = validate_records([daker_record(title=a['title'], host=a['host'],
        **extract_evidence('[참가 자격]\n누구나\n[일정]\n참가 신청 기간\n2026.11.01 09:00 ~ 2026.11.30 10:00'))])
    b['period'] = b['application_period']
    result = recommend({'career_goal': '데이터 분석가'}, [a, b], [{'status': 'success'}], NOW)
    assert len(result['activities']) == 2

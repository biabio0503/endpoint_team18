from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from crawling.dacon.crawler import collect, daker_candidates, merge_cards, status_of
from crawling.dacon.validation import extract_evidence, validate_records, KST
from services.activity_recommendations import recommend


def record(**changes):
    return {'id': 'daker:test', 'title': '데이터 분석 AI 경진대회',
            'url': 'https://daker.ai/public/hackathons/test', 'status': '모집중',
            'start_date': '2026-11-01', 'end_date': '2026-12-31',
            'description': '공공 데이터 분석과 시각화',
            **extract_evidence('[참가 자격]\n일반인, 학생 등 누구나 대회 참가 가능\n[일정]\n참가 신청 기간\n2026.11.01 10:00 ~ 2026.11.13 12:00'), **changes}


def test_registration_is_separate_from_competition_and_submission():
    data = extract_evidence('대회 기간\n2026.11.01 ~ 2026.12.31\n참가 접수\n2026.11.01 10:00 ~ 2026.11.13 12:00\n제출 기간\n2026.11.01 ~ 2026.12.31')
    assert data['application_end_at'] == '2026-11-13T12:00:00+09:00'
    assert extract_evidence('대회 기간\n2026.11.01 ~ 2026.12.31')['application_end_at'] is None
    assert extract_evidence('참가 신청\n제출 기간\n2026.11.01 ~ 2026.12.31')['application_end_at'] is None
    assert extract_evidence('팀 병합 마감\n2026.11.01 ~ 2026.12.31')['application_end_at'] is None
    assert extract_evidence('참가 신청 후 다운로드 가능합니다\n2026.11.01 ~ 2026.12.31')['application_end_at'] is None
    assert extract_evidence('참가 신청이 마감되었습니다.')['application_closed'] is True
    assert extract_evidence('참가 신청 마감 이후 제출물을 평가합니다.')['application_closed'] is False


def test_daker_short_registration_uses_explicit_calendar_year_only():
    text = '참가 접수\n10/26 10:00 ~ 11/20 10:00'
    assert extract_evidence(text)['application_end_at'] is None
    data = extract_evidence(text, ('2026-10-26', '2026-12-07'))
    assert data['application_end_at'] == '2026-11-20T10:00:00+09:00'
    assert data['application_period'] == '10/26 10:00 ~ 11/20 10:00'
    assert '2026' in data['application_evidence']
    assert extract_evidence(text, ('2025-01-01', '2027-12-31'))['application_end_at'] is None


def test_conflicting_registration_is_unverified():
    text = '참가 접수\n2026.11.01 ~ 2026.11.13\n참가 신청 기간\n2026.11.01 ~ 2026.11.20'
    assert extract_evidence(text)['application_end_at'] is None


@pytest.mark.parametrize('target', ['대학생 3학년 이상', '서울 거주 대학생', '누구나 (대학생 제외)',
    '소재 분야 국내 대학(원) 재학생·박사후연구원', '누구나\n단, 대학생 제외'])
def test_eligibility_restrictions_not_erased(target):
    data = extract_evidence('[참가 자격]\n' + target + '\n[문의처]')
    from services.activity_recommendations import eligible_target
    assert not eligible_target(data['target'])


def test_recruiting_daker_and_explicit_closed_retained_for_filtering():
    assert status_of('모집중 마감까지 D-5') == '모집중'
    assert status_of('종료까지 D-16') == '진행중'
    assert status_of('모집중 접수 마감') == '마감'
    items = daker_candidates([{'href': 'https://daker.ai/public/hackathons/test', 'title': 'AI', 'status': '모집중'}])
    assert items[0]['status'] == '모집중'
    closed = {'href': 'https://dacon.io/competitions/official/123/overview/description', 'title': 'AI', 'status': '종료'}
    assert merge_cards([(closed, 'home'), ({**closed, 'status': '진행중'}, 'list')])[0]['status'] == '종료'


def test_validation_identity_dedupe_and_failure():
    item = record()
    rows = validate_records([item, item])
    assert len(rows) == 1 and rows[0]['source'] == 'daker' and rows[0]['original_id'] == 'test'
    with pytest.raises(ValueError):
        validate_records([item, {**item, 'title': 'different'}])
    with pytest.raises(ValueError):
        validate_records([{**item, 'url': 'https://other.test/public/hackathons/test'}])
    assert validate_records([]) == []


def test_deadline_is_rechecked_on_every_recommendation():
    raw = record()
    item = {**raw, 'source': 'daker', 'category': '', 'kind': 'competition', 'period': raw['application_period']}
    profile = {'career_goal': '데이터 분석가'}
    sources = [{'status': 'success'}]
    assert recommend(profile, [item], sources, datetime(2026,11,13,11,59,tzinfo=KST))['activities']
    assert recommend(profile, [item], sources, datetime(2026,11,13,12,0,1,tzinfo=KST))['activities'] == []


def test_render_schedule_and_shared_entrypoint():
    root = Path(__file__).resolve().parents[4]
    cron = (root / 'render.yaml').read_text()
    assert 'type: cron' in cron and 'schedule: "10 0 * * *"' in cron
    assert '\n    rootDir:' not in cron
    assert 'runtime: docker' in cron
    assert 'dockerContext: .' in cron
    assert 'dockerCommand: python -m crawling.activities.run --mode scheduled' in cron
    build = (root / 'crawling/dacon/build.sh').read_text()
    assert 'requirements-server.txt' in build and 'playwright install --with-deps chromium' in build


def test_browser_uses_korean_time_even_on_utc_server(monkeypatch):
    manager = MagicMock()
    browser = manager.__enter__.return_value.chromium.launch.return_value
    browser.new_context.return_value.new_page.return_value.goto.side_effect = RuntimeError('stop before network')
    monkeypatch.setitem(sys.modules, 'playwright', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(sync_playwright=lambda: manager))
    assert collect().status == 'error'
    assert browser.new_context.call_args.kwargs['timezone_id'] == 'Asia/Seoul'

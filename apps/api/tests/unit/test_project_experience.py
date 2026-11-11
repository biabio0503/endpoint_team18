"""Source verification and matching never require an external service."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from classbridge import (DETAILS, ROWS, ROLE_DESCRIPTION, candidate, classbridge_document,
                        classbridge_original_order_document, classbridge_extraction, ocr_document, response)
from services import project_experience as service
from services.gemini import GeminiError
from services.gemini_projects import extract_project_experiences
from services.project_experience_schemas import DocumentExperience, ExperienceAnswer
from experience_activity_regressions import (EXPERIENCES, PROJECT_TEXT, fixed_extraction,
                                            NEGATION_CASES, negation_extraction)


def document(text='제가 Python으로 전처리 코드를 작성했습니다.'):
    return {'document_id': 'doc-1', 'extraction_revision': 2, 'extracted_text': text,
            'segments': [{'start': 0, 'end': len(text), 'page': 2}]}


def extraction(doc, scope='personal', **changes):
    item = {'skill_name': 'Python 3', 'category': 'programming_language', 'activity': '전처리 코드 작성',
            'contribution_scope': scope, 'evidence_text': doc['extracted_text'], **changes}
    return DocumentExperience(document_id=doc['document_id'], extraction_revision=doc['extraction_revision'], experiences=[item])


@pytest.mark.parametrize('text,scopes', NEGATION_CASES,
                         ids=['performed', 'never_performed', 'participant_problem', 'mixed_activities'])
@pytest.mark.parametrize('geometry', [False, True], ids=['text', 'bbox'])
def test_negation_fixed_candidates_follow_source_activity(text, scopes, geometry):
    doc = document(text)
    if geometry:
        doc['segments'][0]['bbox'] = [0, 0, 600, 20]
    with patch('services.gemini_projects._generate', return_value=negation_extraction(doc)) as model:
        result = service.analyze_document(doc)
    model.assert_called_once()
    assert result['status'] == 'success' and result['errors'] == []
    items = {item['skill_name']: item for item in result['experiences']}
    assert set(items) == set(scopes)
    for name, scope in scopes.items():
        item = items[name]
        assert item['model_contribution_scope'] == 'personal'
        assert item['contribution_scope'] == scope
        assert item['contribution_basis']['reason'] == (
            'document_personal' if scope == 'personal' else 'not_performed')
        assert item['activity'] == item['evidence_text'] == text
        assert text[item['evidence_start']:item['evidence_end']] == text
        assert service.compare_skill([{**item, 'user_answer': None}])[0] == (
            'document_supported' if scope == 'personal' else 'needs_confirmation')


@pytest.mark.parametrize('text,scopes', [
    ('저는 사용자 인터뷰를 진행했지만 Figma로 프로토타입을 제작하지 않았습니다.',
     {'사용자 인터뷰': 'personal', 'Figma': 'unknown'}),
    ('저는 Figma로 프로토타입을 만든 적은 없지만 사용자 인터뷰를 진행했습니다.',
     {'Figma': 'unknown', '사용자 인터뷰': 'personal'}),
    ('저는 Figma를 사용하지 않았고 사용자 인터뷰를 진행했습니다.',
     {'Figma': 'unknown', '사용자 인터뷰': 'personal'}),
    ('저는 사용자 인터뷰를 진행했습니다. Figma로 프로토타입을 만든 적이 없습니다.',
     {'사용자 인터뷰': 'personal', 'Figma': 'unknown'}),
    ('저는 사용자 인터뷰와 사용성 테스트를 진행한 적이 없습니다.',
     {'사용자 인터뷰': 'unknown', '사용성 테스트': 'unknown'}),
    ('저는 사용자 인터뷰를 진행해 사용자가 기능을 사용하지 못하는 이유를 기록했습니다.',
     {'사용자 인터뷰': 'personal'}),
    ('저는 사용자 인터뷰를 진행하여 사용자가 기능을 사용하지 않는 이유를 기록했습니다.',
     {'사용자 인터뷰': 'personal'}),
    ('저는 사용자 인터뷰를 진행해 본 적이 없습니다.', {'사용자 인터뷰': 'unknown'}),
    ('저는 사용자 인터뷰를 진행한 경험이 없습니다.', {'사용자 인터뷰': 'unknown'}),
    ('저는 Figma로 프로토타입을 만들어 본 적은 없습니다.', {'Figma': 'unknown'}),
    ('저는 Figma로 프로토타입을 만든 적도 없습니다.', {'Figma': 'unknown'}),
])
def test_negation_stays_with_the_named_activity(text, scopes):
    doc = document(text)
    model = response(doc, [candidate(name, text) for name in scopes])
    with patch('services.gemini_projects._generate', return_value=model):
        result = service.analyze_document(doc)
    assert result['status'] == 'success' and not result['errors']
    assert {item['skill_name']: item['contribution_scope'] for item in result['experiences']} == scopes


def test_incident_fixed_candidates_survive_real_analysis_pipeline():
    doc = document(PROJECT_TEXT)
    with patch('services.gemini_projects._generate', return_value=fixed_extraction(doc)) as model:
        result = service.analyze_document(doc)
    model.assert_called_once()
    assert result['status'] == 'success' and not result['errors']
    items = {item['skill_name']: item for item in result['experiences']}
    assert set(items) == {name for name, _ in EXPERIENCES}
    for name, quote in EXPERIENCES[:4]:
        item = items[name]
        assert item['contribution_scope'] == 'personal'
        assert item['activity'] == item['evidence_text'] == quote
        assert PROJECT_TEXT[item['evidence_start']:item['evidence_end']] == quote
        assert service.compare_skill([{**item, 'user_answer': None}])[0] == 'document_supported'
    assert items['React']['contribution_scope'] != 'personal'
    assert items['Framer']['contribution_scope'] == 'unknown'
    assert items['Framer']['contribution_basis']['reason'] == 'not_performed'


def test_missing_model_candidates_are_distinct_from_server_rejection():
    doc = document(PROJECT_TEXT)
    model = fixed_extraction(doc)
    model.experiences = []
    with patch('services.gemini_projects._generate', return_value=model):
        result = service.analyze_document(doc)
    assert result['status'] == 'success'
    assert result['experiences'] == result['errors'] == []


@pytest.mark.parametrize('text,scope', [
    ('저는 Figma로 프로토타입을 만들었습니다.', 'personal'),
    ('저는 Figma로 프로토타입을 제작했습니다.', 'personal'),
    ('저는 Figma로 테스트를 진행했습니다.', 'personal'),
    ('Figma로 프로토타입을 만들었습니다.', 'unknown'),
    ('담당자 김학생은 Figma로 프로토타입을 제작했습니다.', 'unknown'),
    ('팀원 정우는 Figma로 테스트를 진행했습니다.', 'team'),
    ('저는 Figma로 프로토타입을 만들 예정입니다.', None),
    ('저는 Figma로 프로토타입을 제작하지 않았습니다.', 'unknown'),
    ('저는 Figma로 테스트를 진행하지 않았습니다.', 'unknown'),
])
def test_natural_actions_still_require_actor_and_performance(text, scope):
    doc = document(text)
    items, errors = service.verify_experiences(doc, extraction(doc, skill_name='Figma'), 'a')
    if scope is None:
        assert not items and errors[0]['code'] == 'activity_not_in_evidence'
    else:
        assert not errors and items[0]['contribution_scope'] == scope


@pytest.mark.parametrize('name,text,expected', [
    ('사용성 테스트', '사용성 테스트를 진행했습니다.', True),
    ('사용자 인터뷰', '사용자 인터뷰로 요구를 파악했습니다.', True),
    ('사용자 인터뷰', '사용자 인터뷰어를 모집했습니다.', False),
    ('사용성 테스트', '비사용성 테스트를 진행했습니다.', False),
    ('Java', 'JavaScript로 만들었습니다.', False),
    ('SQL', 'PostgreSQL로 만들었습니다.', False),
])
def test_skill_particles_do_not_allow_other_skill_substrings(name, text, expected):
    from services.project_evidence import names_skill
    assert names_skill(name, text) is expected


@pytest.mark.parametrize('scope,text,expected', [
    ('personal', '제가 Python으로 전처리 코드를 작성했습니다.', 'personal'),
    ('team', '팀에서는 Python을 사용했습니다.', 'team'),
    ('unknown', 'Python 전처리 코드 작성', 'unknown'),
    ('personal', '담당자 김학생은 Python 코드를 작성했습니다.', 'unknown'),
])
def test_actor_and_source_offsets(scope, text, expected):
    doc = document(text)
    verified, errors = service.verify_experiences(doc, extraction(doc, scope), 'analysis')
    assert not errors and len(verified) == 1
    item = verified[0]
    assert item['contribution_scope'] == expected
    assert item['skill_name'] == 'Python'
    assert text[item['evidence_start']:item['evidence_end']] == item['evidence_text']
    assert item['locations'][0]['page'] == 2


@pytest.mark.parametrize('change,code', [
    ({'evidence_text': 'I wrote Python code that is not in the source.'}, 'evidence_not_in_source'),
    ({'skill_name': 'Java'}, 'skill_not_in_evidence'),
])
def test_hallucinated_fields_rejected(change, code):
    doc = document()
    verified, errors = service.verify_experiences(doc, extraction(doc, **change), 'analysis')
    assert verified == [] and errors == [{'code': code, 'candidate_index': 0,
                                         'skill_name': change.get('skill_name', 'Python 3')}]


@pytest.mark.parametrize('role,output,expected_role,expected_output', [
    ('팀장', 'REST API 9개', None, 'REST API 9개'),
    ('설계', 'REST API 12개', '설계', None),
    ('팀장', 'REST API 12개', None, None),
])
def test_optional_fields_are_independent_and_do_not_fail_analysis(role, output, expected_role, expected_output):
    doc = document(DETAILS['FastAPI'])
    model = response(doc, [candidate('FastAPI', doc['extracted_text'], role=role, output=output,
                                     activity='팀장으로 API 12개 구현')])
    with patch.object(service, 'extract_project_experiences', return_value=model):
        result = service.analyze_document(doc)
    assert result['status'] == 'success' and result['errors'] == []
    item, = result['experiences']
    assert (item['role'], item['output']) == (expected_role, expected_output)
    assert item['activity'] == DETAILS['FastAPI']
    assert '12' not in item['activity'] and '팀장' not in item['activity']
    assert {a['field'] for a in item['validation_adjustments']} == (
        {'activity'} | ({'role'} if expected_role is None else set()) | ({'output'} if expected_output is None else set()))


@pytest.mark.parametrize('quote', ['FastAPI', 'FastAPI 라이브러리 목록입니다.', 'FastAPI API 9개 구현 예정'])
def test_activity_without_performed_work_is_rejected(quote):
    doc = document(quote)
    result, errors = service.verify_experiences(doc, response(doc, [candidate('FastAPI', quote,
        activity='팀장으로 API 12개 구현')]), 'a')
    assert result == []
    assert errors[0]['code'] == 'activity_not_in_evidence'
    assert errors[0]['skill_name'] == 'FastAPI' and errors[0]['candidate_index'] == 0


@pytest.mark.parametrize('field,value,code', [('document_id', 'other-user-doc', 'unexpected_document_id'),
    ('extraction_revision', 4, 'extraction_revision_mismatch')])
def test_id_and_revision_must_match(field, value, code):
    doc = document()
    value = extraction(doc).model_copy(update={field: value})
    assert service.verify_experiences(doc, value, 'a') == ([], [{'code': code}])


def test_multiple_segments_and_duplicate_observations():
    doc = document('I used Python.\nI made charts.')
    doc['segments'] = [{'start': 0, 'end': 14, 'paragraph': 1}, {'start': 15, 'end': 29, 'paragraph': 2}]
    result = extraction(doc)
    result.experiences *= 2
    verified, errors = service.verify_experiences(doc, result, 'a')
    assert len(verified) == 1 and len(verified[0]['locations']) == 2 and not errors


@pytest.mark.parametrize('left,right', [('Python 3', 'Python'), ('Postgres', 'PostgreSQL'), ('AWS', 'Amazon Web Services')])
def test_explicit_aliases(left, right):
    assert service.skill_key(left) == service.skill_key(right)


@pytest.mark.parametrize('left,right', [('Java', 'JavaScript'), ('SQL', 'PostgreSQL'), ('React', 'React Native'), ('PyTorch', 'TensorFlow')])
def test_distinct_skills(left, right):
    assert service.skill_key(left) != service.skill_key(right)


@pytest.mark.parametrize('scope,answer,status', [
    ('personal', None, 'document_supported'), ('team', None, 'needs_confirmation'), ('unknown', None, 'needs_confirmation'),
    ('team', {'status': 'confirmed'}, 'confirmed_experience'),
    ('personal', {'status': 'unknown'}, 'needs_confirmation'),
    ('personal', {'status': 'no_experience'}, 'no_experience'),
    ('team', {'status': 'corrected', 'correction': {'contribution_scope': 'personal'}}, 'confirmed_experience'),
    ('personal', {'status': 'corrected', 'correction': {'contribution_scope': 'team'}}, 'needs_confirmation'),
])
def test_status_classification(scope, answer, status):
    assert service.compare_skill([{'contribution_scope': scope, 'user_answer': answer}])[0] == status


def test_absence_unknown_and_conflicting_user_answers():
    assert service.compare_skill([])[0] == 'not_verified'
    assert service.compare_skill([], {'status': 'no_experience'})[0] == 'no_experience'
    assert service.compare_skill([], {'status': 'unknown'})[0] == 'needs_confirmation'
    assert service.compare_skill([{'user_answer': {'status': 'confirmed'}}], {'status': 'no_experience'})[0] == 'needs_confirmation'


def test_actual_gemini_transport_minimal_payload_and_configured_model():
    doc = {**document(), 'owner_id': 'secret', 'original_filename': 'private-name', 'binary': b'PDF'}
    client = Mock()
    client.models.generate_content.return_value = Mock(text=extraction(doc).model_dump_json())
    with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key', 'GEMINI_MODEL': 'operator-selected-model'}), patch('google.genai.Client', return_value=client):
        extract_project_experiences(doc)
    args = client.models.generate_content.call_args.kwargs
    assert args['model'] == 'operator-selected-model'
    payload = json.loads(args['contents'])
    assert set(payload) == {'document_id', 'extraction_revision', 'extracted_text', 'segments'}
    assert payload['segments'] == doc['segments']
    client.close.assert_called_once()


def test_gemini_429_is_bounded_and_never_logs_body(capsys):
    error = RuntimeError('secret-body')
    error.code = 429
    client = Mock()
    client.models.generate_content.side_effect = error
    with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}), patch('google.genai.Client', return_value=client), patch('services.gemini_jobs.time.sleep'):
        result = service.analyze_document(document())
    assert result['status'] == 'error' and result['errors'][0]['code'] == 'gemini_rate_limited'
    assert client.models.generate_content.call_count == 2
    assert 'secret-body' not in capsys.readouterr().out


def test_oversized_document_is_not_silently_truncated():
    with patch.object(service, 'extract_project_experiences') as model:
        result = service.analyze_document(document('x' * 60001))
    assert result['errors'] == [{'code': 'document_too_long'}]
    model.assert_not_called()


def test_answer_corrections_are_strict_and_separate():
    with pytest.raises(ValueError):
        ExperienceAnswer(expected_input_revision=1, status='corrected')
    with pytest.raises(ValueError):
        ExperienceAnswer(expected_input_revision=1, status='confirmed', correction={'skill_name': 'Python', 'activity': 'code', 'contribution_scope': 'personal'})
    with pytest.raises(ValueError):
        ExperienceAnswer(expected_input_revision=True, status='unknown')


@pytest.mark.parametrize('coordinate', ['page', 'paragraph'])
def test_scrambled_ocr_table_and_classbridge_details(coordinate):
    doc = classbridge_document(coordinate)
    items, errors = service.verify_experiences(doc, classbridge_extraction(doc), 'a')
    assert errors == [] and len(items) == 13
    for tech, label, names in ROWS:
        for name in names:
            item = next(i for i in items if i['evidence_text'] == tech and service.skill_key(i['skill_name']) == service.skill_key(name))
            assert item['contribution_scope'] == ('team' if label == '팀원 담당' else 'personal')
            assert item['activity'] == tech + ' · ' + label
            assert item['contribution_basis']['method'] == 'table_bbox'
            assert item['contribution_basis']['context'][-1]['text'] == label
            # The actual quote remains the technology cell, never header + detached cells.
            assert item['evidence_text'] == doc['extracted_text'][item['evidence_start']:item['evidence_end']]
            for context in item['contribution_basis']['context']:
                assert context['text'] == doc['extracted_text'][context['start']:context['end']]
                assert coordinate in context['locations'][0]
    for name, detail in DETAILS.items():
        item = next(i for i in items if i['evidence_text'] == detail)
        assert item['activity'] == detail
        assert item['contribution_scope'] == 'personal'
        assert item['contribution_basis']['method'] == 'section_bbox'
        assert item['role'] is None and item['output'] is None
        assert service.compare_skill([{**item, 'user_answer': None}])[0] == 'document_supported'
        assert service.compare_skill([{**item, 'user_answer': {'status': 'confirmed'}}])[0] == 'confirmed_experience'


def test_adjacent_team_row_cannot_attach_to_fastapi():
    doc = classbridge_document()
    # Drop the true FastAPI label's geometry: nearby team row is NOT a substitute.
    doc['segments'] = [s for s in doc['segments'] if doc['extracted_text'][s['start']:s['end']] != '직접 구현']
    item, = service.verify_experiences(doc, response(doc, [candidate('FastAPI', 'FastAPI / Redis')]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'
    assert item['contribution_basis']['context'] == []


@pytest.mark.parametrize('change', ['page', 'paragraph', 'image_ref', 'far_away', 'merged_row'])
def test_geometry_requires_same_table_and_unique_row(change):
    doc = classbridge_document('paragraph' if change == 'paragraph' else 'page')
    for segment in doc['segments']:
        value = doc['extracted_text'][segment['start']:segment['end']]
        if value == '본인 기여 여부' and change in ('page', 'paragraph', 'image_ref'):
            segment[change] = 99
        if value == 'FastAPI / Redis' and change == 'far_away':
            segment['bbox'] = [[150, 800], [410, 820]]
        if value == '직접 구현' and change == 'merged_row':
            segment['bbox'] = [[450, 140], [550, 220]]
    items, errors = service.verify_experiences(doc, response(doc, [candidate('FastAPI', 'FastAPI / Redis')]), 'a')
    if change == 'far_away':
        # A detached technology mention has neither an activity nor table context.
        assert items == [] and errors[0]['code'] == 'activity_not_in_evidence'
    else:
        assert not errors and items[0]['contribution_scope'] == 'unknown'


def test_without_coordinates_ambiguous_ocr_rows_stay_unknown():
    doc = classbridge_document()
    doc['segments'] = [{k: v for k, v in s.items() if k != 'bbox'} for s in doc['segments']]
    items, errors = service.verify_experiences(doc, classbridge_extraction(doc), 'a')
    assert not errors
    for item in items:
        if item['evidence_text'] in [r[0] for r in ROWS]:
            assert item['contribution_scope'] == 'unknown'
            assert item['contribution_basis']['context'] == []
            assert item['activity'] == item['evidence_text']


@pytest.mark.parametrize('separator', [' | ', '\t', '  '])
def test_without_coordinates_only_explicit_rows_establish_contribution(separator):
    text = separator.join(['기술 스택', '본인 기여 여부']) + '\n'
    text += '\n'.join(separator.join([tech, label]) for tech, label, _ in ROWS)
    doc = document(text)
    result = response(doc, [candidate(name, tech) for tech, _, names in ROWS for name in names])
    items, errors = service.verify_experiences(doc, result, 'a')
    assert not errors and len(items) == 8
    for item in items:
        assert item['contribution_scope'] == ('team' if item['skill_name'] in ('Next.js', 'TypeScript') else 'personal')
        assert item['contribution_basis']['method'] == 'table_row'
    assert all('일부 설정' in i['activity'] and '전체' not in i['activity'] for i in items
               if i['skill_name'] in ('Docker', 'GitHub Actions'))


@pytest.mark.parametrize('geometry', [True, False])
def test_personal_section_stops_and_explicit_negatives_override_heading(geometry):
    cells = [('본인이 직접 수행한 작업', 1, 50, 50, 300),
             (DETAILS['pytest'], 1, 70, 90, 450),
             ('Next.js 화면 구현 — 팀원 담당', 1, 70, 130, 450),
             ('Docker 배포 미수행', 1, 70, 170, 450),
             ('팀 전체 성과', 1, 50, 210, 300),
             ('팀 전체 서비스 테스트: 사용자 48명', 1, 70, 250, 450),
             ('Playwright 테스트 48개 작성', 1, 70, 290, 450)]
    doc = ocr_document(cells)
    if not geometry:
        doc['segments'] = []
    model = response(doc, [candidate(name, quote) for name, quote in [
        ('pytest', DETAILS['pytest']), ('Next.js', cells[2][0]), ('Docker', cells[3][0]), ('Playwright', cells[-1][0])]])
    items, errors = service.verify_experiences(doc, model, 'a')
    assert not errors
    assert [i['contribution_scope'] for i in items] == ['personal', 'team', 'unknown', 'unknown']
    assert items[2]['contribution_basis']['reason'] == 'not_performed'
    assert not items[-1]['contribution_basis']['context']


def test_scrambled_section_uses_coordinates_and_repeated_quote_is_ambiguous():
    doc = ocr_document([(DETAILS['pytest'], 1, 70, 90, 450),
        ('다음 섹션', 1, 50, 130, 300), ('본인이 직접 수행한 작업', 1, 50, 50, 300)])
    model = response(doc, [candidate('pytest', DETAILS['pytest'])])
    assert service.verify_experiences(doc, model, 'a')[0][0]['contribution_scope'] == 'personal'
    doc['extracted_text'] += DETAILS['pytest']
    item = service.verify_experiences(doc, model, 'a')[0][0]
    assert item['contribution_scope'] == 'unknown'
    assert item['contribution_basis']['reason'] == 'ambiguous_source_location'


def test_flattened_multiple_rows_never_assign_the_adjacent_actor():
    text = '기술 스택 본인 기여 여부 FastAPI 직접 구현 Next.js 팀원 담당'
    doc = document(text)
    item, = service.verify_experiences(doc, response(doc, [candidate('FastAPI', text)]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'
    assert item['activity'] == 'FastAPI · 수행 내용 미확인'


@pytest.mark.parametrize('prefix', ['- ', '1. ', '• '])
def test_numbered_and_bulleted_personal_lists(prefix):
    text = '본인이 직접 수행한 작업\n' + prefix + DETAILS['pytest']
    doc = document(text)
    item, = service.verify_experiences(doc, response(doc, [candidate('pytest', DETAILS['pytest'])]), 'a')[0]
    assert item['contribution_scope'] == 'personal'


def test_blank_paragraph_does_not_extend_personal_section():
    doc = document('본인이 직접 수행한 작업\n' + DETAILS['pytest'] + '\n\n' + DETAILS['FastAPI'])
    item, = service.verify_experiences(doc, response(doc, [candidate('FastAPI', DETAILS['FastAPI'])]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'


def test_blank_line_separates_tables_and_negative_cell_overrides_personal_header():
    doc = document('기술 스택 | 본인 기여 여부\nDocker | 미수행\n\nFastAPI | 직접 구현')
    items, errors = service.verify_experiences(doc, response(doc, [candidate('Docker', 'Docker'),
        candidate('FastAPI', 'FastAPI')]), 'a')
    assert len(items) == 1 and items[0]['contribution_scope'] == 'unknown'
    assert items[0]['contribution_basis']['reason'] == 'not_performed'
    assert errors[0]['skill_name'] == 'FastAPI' and errors[0]['code'] == 'activity_not_in_evidence'


def test_other_column_does_not_extend_personal_section():
    doc = ocr_document([('본인이 직접 수행한 작업', 1, 50, 50, 300), (DETAILS['pytest'], 1, 600, 90, 450)])
    item, = service.verify_experiences(doc, response(doc, [candidate('pytest', DETAILS['pytest'])]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'


@pytest.mark.parametrize('coordinate', ['page', 'paragraph'])
def test_original_order_role_description_preserves_five_personal_activities(coordinate):
    doc = classbridge_original_order_document(coordinate)
    model = classbridge_extraction(doc)
    outside = 'Playwright 서비스 테스트 48개 작성'
    model.experiences.extend(response(doc, [candidate('Playwright', outside)]).experiences)
    items, errors = service.verify_experiences(doc, model, 'a')
    assert not errors
    for detail in DETAILS.values():
        item = next(i for i in items if i['evidence_text'] == detail)
        assert item['activity'] == detail
        assert item['contribution_scope'] == 'personal'
        assert item['contribution_basis']['method'] == 'section_bbox'
        assert item['contribution_basis']['reason'] == 'document_personal'
        assert [c['text'] for c in item['contribution_basis']['context']] == [
            '본인이 직접 수행한 작업', ROLE_DESCRIPTION]
        assert doc['extracted_text'][item['evidence_start']:item['evidence_end']] == detail
        for context in item['contribution_basis']['context']:
            assert doc['extracted_text'][context['start']:context['end']] == context['text']
    team = [i for i in items if i['skill_name'] in ('Next.js', 'TypeScript')]
    assert len(team) == 2 and all(i['contribution_scope'] == 'team' for i in team)
    assert all(i['contribution_basis']['method'] == 'table_bbox' for i in team)
    after_table = next(i for i in items if i['skill_name'] == 'Playwright')
    assert after_table['contribution_scope'] == 'unknown'
    assert after_table['contribution_basis']['reason'] == 'actor_unspecified'
    assert after_table['contribution_basis']['context'] == []


@pytest.mark.parametrize('geometry', [True, False])
@pytest.mark.parametrize('boundary', ['팀 전체 성과', '4. 시스템 개발', '4) 운영 및 테스트',
                                     '기술 스택 | 본인 기여 여부'])
def test_role_description_does_not_extend_context_past_next_section(boundary, geometry):
    doc = ocr_document([('본인이 직접 수행한 작업', 1, 50, 50, 300),
        (ROLE_DESCRIPTION, 1, 70, 90, 500), ('① ' + DETAILS['pytest'], 1, 70, 130, 450),
        (boundary, 1, 50, 170, 500), ('② ' + DETAILS['FastAPI'], 1, 70, 210, 450)])
    if not geometry:
        doc['segments'] = []
    items, errors = service.verify_experiences(doc, response(doc, [candidate(name, DETAILS[name])
        for name in ('pytest', 'FastAPI')]), 'a')
    assert not errors
    assert [i['contribution_scope'] for i in items] == ['personal', 'unknown']
    assert items[-1]['contribution_basis']['reason'] == 'actor_unspecified'


@pytest.mark.parametrize('geometry', [True, False])
def test_ambiguous_table_reason_is_local_to_table(geometry):
    doc = classbridge_original_order_document()
    doc['extracted_text'] = doc['extracted_text'].replace('본인이 직접 수행한 작업', '프로젝트 개발 작업 목록')
    # Rebuild offsets after replacing the heading; keep the original OCR coordinates.
    cells = [(line, 1, s['bbox'][0][0], s['bbox'][0][1], s['bbox'][1][0] - s['bbox'][0][0])
             for line, s in zip(doc['extracted_text'].splitlines(), doc['segments'])]
    doc = ocr_document(cells)
    if geometry:
        doc['segments'] = [s for s in doc['segments'] if doc['extracted_text'][s['start']:s['end']] != '직접 구현']
    else:
        doc['segments'] = []
    model = response(doc, [candidate('pytest', DETAILS['pytest']), candidate('FastAPI', 'FastAPI / Redis')])
    items, errors = service.verify_experiences(doc, model, 'a')
    assert not errors
    assert [i['contribution_scope'] for i in items] == ['unknown', 'unknown']
    assert [i['contribution_basis']['reason'] for i in items] == ['actor_unspecified', 'ambiguous_table_row']


@pytest.mark.parametrize('geometry', [True, False])
def test_known_row_with_unknown_contribution_is_not_ambiguous(geometry):
    doc = ocr_document([('기술 스택', 1, 150, 100, 100), ('본인 기여 여부', 1, 450, 100, 130),
                        ('FastAPI', 1, 150, 140, 200), ('확인 필요', 1, 450, 140, 130)])
    if not geometry:
        doc = document('기술 스택 | 본인 기여 여부\nFastAPI | 확인 필요')
    item, = service.verify_experiences(doc, response(doc, [candidate('FastAPI', 'FastAPI')]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'
    assert item['contribution_basis']['reason'] == 'actor_unspecified'
    assert item['contribution_basis']['method'] == ('table_bbox' if geometry else 'table_row')


@pytest.mark.parametrize('description', ['설명: 백엔드 API 개발', '다음 단계: 백엔드 API 개발'])
def test_other_colon_lines_still_end_the_personal_section(description):
    doc = document('본인이 직접 수행한 작업\n' + description + '\n① ' + DETAILS['pytest'])
    item, = service.verify_experiences(doc, response(doc, [candidate('pytest', DETAILS['pytest'])]), 'a')[0]
    assert item['contribution_scope'] == 'unknown'

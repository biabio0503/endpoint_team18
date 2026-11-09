"""Detailed failures must stay useful without retaining untrusted values."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from services.roadmap_generation import model_input, validate_result
from services.roadmap_validation import RoadmapValidationError, error_metadata, parse_response, stored_error_code
from test_roadmap_generation import basis, output


def check(raw, b, code, path):
    with pytest.raises(RoadmapValidationError) as caught:
        validate_result(raw, b)
    error = caught.value
    assert error.code == 'gemini_invalid_response'
    assert error.diagnostic == {'detail_code': code, 'field_path': path}
    assert error_metadata(stored_error_code(error)) == {
        'error_code': error.code, 'error_detail_code': code}
    return error


@pytest.mark.parametrize('field,value,code', [
    ('action', '', 'schema_bounds_invalid'),
    ('completion_criteria', ' ', 'schema_bounds_invalid'),
    ('deliverable', 42, 'schema_type_invalid'),
    ('task_id', 'bad id!', 'schema_value_invalid'),
    ('task_type', 'invented', 'schema_value_invalid'),
])
def test_schema_failure_path(field, value, code):
    raw = output()
    raw['roadmap'][0]['tasks'][0][field] = value
    check(raw, basis(), code, f'$.roadmap[0].tasks[0].{field}')


def test_schema_missing_and_untrusted_extra_field_never_logged():
    raw = output()
    del raw['roadmap'][0]['tasks'][0]['deliverable']
    check(raw, basis(), 'schema_field_missing', '$.roadmap[0].tasks[0].deliverable')
    raw = output()
    raw['roadmap'][0]['secret-token-project-full-text'] = 'sensitive'
    error = check(raw, basis(), 'schema_extra_field', '$.roadmap[0].unknown_field')
    assert 'sensitive' not in str(error) + repr(error.diagnostic)
    assert 'secret-token' not in repr(error.diagnostic)
    with pytest.raises(RoadmapValidationError) as caught:
        parse_response('{"private-document": broken')
    assert caught.value.detail_code == 'schema_json_invalid'
    assert 'private-document' not in str(caught.value) + repr(caught.value.diagnostic)


@pytest.mark.parametrize('field,value,code', [
    ('course_id', 'invented', 'course_not_allowed'),
    ('course_id', 'same-name-completed', 'course_completed'),
    ('related_skills', ['SQL', 'SQL'], 'skill_duplicate'),
    ('related_skills', ['Excel'], 'skill_not_allowed'),
    ('evidence_refs', ['comparison:sql', 'comparison:sql'], 'evidence_duplicate'),
    ('evidence_refs', ['private-token'], 'evidence_not_provided'),
    ('course_evidence', 'Database', 'course_evidence_mismatch'),
    ('reason', '반드시 공부', 'prohibited_expression'),
])
def test_course_failure_codes(field, value, code):
    raw = output()
    raw['recommended_courses'][0][field] = value
    indexed = field in ('related_skills', 'evidence_refs') and code not in ('skill_duplicate', 'evidence_duplicate')
    check(raw, basis(), code, f'$.recommended_courses[0].{field}' + ('[0]' if indexed else ''))


@pytest.mark.parametrize('field,value,code', [
    ('order', 2, 'step_order_invalid'),
    ('depends_on', ['step-1'], 'dependency_not_previous'),
    ('depends_on', ['step-1', 'step-1'], 'dependency_duplicate'),
    ('related_course_ids', ['db', 'db'], 'related_course_duplicate'),
    ('related_course_ids', ['unknown'], 'related_course_not_recommended'),
])
def test_step_failure_codes(field, value, code):
    raw = output()
    raw['roadmap'][0][field] = value
    indexed = code in ('dependency_not_previous', 'related_course_not_recommended')
    check(raw, basis(), code, f'$.roadmap[0].{field}' + ('[0]' if indexed else ''))


def test_experience_state_action_and_verification_wording():
    raw = output()
    raw['roadmap'][0]['skill_targets'][0]['student_status'] = 'confirmed_experience'
    check(raw, basis(), 'experience_status_mismatch', '$.roadmap[0].skill_targets[0].student_status')
    raw = output()
    raw['roadmap'][0]['skill_targets'][0]['action_type'] = 'deepen'
    check(raw, basis(), 'experience_action_mismatch', '$.roadmap[0].skill_targets[0].action_type')
    for field, value, code in [('task_type', 'apply', 'task_type_mismatch'),
                             ('action', 'SQL 자료를 정리한다.', 'experience_verification_wording')]:
        raw = output('document_supported')
        raw['roadmap'][0]['tasks'][0][field] = value
        check(raw, basis('document_supported'), code, f'$.roadmap[0].tasks[0].{field}')


@pytest.mark.parametrize('kind', ['step', 'task', 'action', 'course', 'equivalent'])
def test_duplicate_codes(kind):
    raw, b = output(), basis()
    if kind == 'step':
        raw['roadmap'].append(deepcopy(raw['roadmap'][0]))
        code, path = 'step_id_duplicate', '$.roadmap[1].step_id'
    elif kind in ('task', 'action'):
        task = deepcopy(raw['roadmap'][0]['tasks'][0])
        if kind == 'action': task['task_id'] = 'task-2'
        raw['roadmap'][0]['tasks'].append(task)
        code, path = ('task_id_duplicate', '$.roadmap[0].tasks[1].task_id') if kind == 'task' else (
            'task_action_duplicate', '$.roadmap[0].tasks[1].action')
    else:
        course = deepcopy(raw['recommended_courses'][0])
        if kind == 'equivalent':
            b['courses'].append({**b['courses'][0], 'course_id': 'db-alt', 'verified_equivalent_ids': ['db']})
            course['course_id'] = 'db-alt'
        raw['recommended_courses'].append(course)
        code, path = ('course_duplicate' if kind == 'course' else 'course_equivalent_duplicate'), '$.recommended_courses[1].course_id'
    check(raw, b, code, path)


def test_old_error_code_compatibility():
    for code in (None, 'gemini_invalid_response', 'gemini_rate_limited'):
        assert error_metadata(code) == {'error_code': code}


def test_references_must_be_the_output_comparison_refs_not_hidden_or_source_evidence():
    for provided in (False, True):
        b, raw = basis(), output()
        b['evidence']['job:sql'] = {'skill_name': 'SQL'}
        if provided: b['skills'][0]['job_refs'] = ['job:sql']
        raw['roadmap'][0]['evidence_refs'].append('job:sql')
        check(raw, b, 'evidence_ref_not_allowed' if provided else 'evidence_not_provided', '$.roadmap[0].evidence_refs[1]')


def test_learning_and_deepening_do_not_accept_experience_verification_tasks():
    for status in ('no_experience', 'confirmed_experience'):
        raw = output(status)
        raw['roadmap'][0]['tasks'][0]['task_type'] = 'verify_experience'
        check(raw, basis(status), 'task_type_mismatch', '$.roadmap[0].tasks[0].task_type')


def test_model_receives_verified_equivalents_and_explicit_task_contract():
    b = basis('document_supported')
    b['courses'][0]['verified_equivalent_ids'] = ['db-alt']
    b['courses'].append({**b['courses'][0], 'course_id': 'db-alt', 'verified_equivalent_ids': ['db']})
    data = model_input(b)
    assert data['eligible_courses'][0]['verified_equivalent_ids'] == ['db-alt']
    assert data['skills'][0]['allowed_task_types'] == ['verify_experience']
    assert data['skills'][0]['action_required_terms'] == ['경험', '확인']


def test_reference_completeness_and_related_skill_checks():
    b = basis()
    b['skills'].append({'skill_name': 'Python', 'student_status': 'no_experience', 'comparison_ref': 'comparison:python'})
    b['evidence']['comparison:python'] = {'skill_name': 'Python', 'student_status': 'no_experience'}
    raw = output()
    raw['roadmap'][0]['evidence_refs'].append('comparison:python')
    check(raw, b, 'evidence_skill_mismatch', '$.roadmap[0].evidence_refs[1]')
    raw = output()
    raw['roadmap'][0]['skill_targets'].append({'skill_name': 'Python', 'student_status': 'no_experience', 'action_type': 'learn'})
    check(raw, b, 'evidence_comparison_missing', '$.roadmap[0].evidence_refs')
    raw = output()
    raw['recommended_courses'][0].update(related_skills=['Python'], evidence_refs=['comparison:python'])
    check(raw, b, 'related_course_skill_mismatch', '$.roadmap[0].related_course_ids[0]')
    raw = output()
    raw['roadmap'][0]['skill_targets'].append({'skill_name': 'Python', 'student_status': 'no_experience', 'action_type': 'verify_experience'})
    raw['roadmap'][0]['evidence_refs'].append('comparison:python')
    check(raw, b, 'step_action_types_mixed', '$.roadmap[0].skill_targets')


def test_completed_equivalent_and_basic_practice_are_rejected():
    b = basis()
    b['courses'][0]['equivalent_completed'] = True
    check(output(), b, 'course_equivalent_completed', '$.recommended_courses[0].course_id')
    raw = output('confirmed_experience')
    raw['roadmap'][0]['tasks'][0]['task_type'] = 'practice'
    check(raw, basis('confirmed_experience'), 'confirmed_experience_basic_practice', '$.roadmap[0].tasks[0].task_type')
    raw = output()
    raw['roadmap'][0]['tasks'][0]['deliverable'] = '수강 기록'
    check(raw, basis(), 'task_course_claim', '$.roadmap[0].tasks[0].deliverable')


def test_partial_job_analysis_is_a_valid_partial_result():
    b = basis('confirmed_experience')
    b.update(job_status='partial', job_summary={'analyzed_jobs': 19, 'failed_jobs': 1})
    result = validate_result(output('confirmed_experience'), b)
    assert result['status'] == 'partial'
    assert result['basis']['job_summary'] == b['job_summary']
    assert result['roadmap'][0]['skill_targets'][0]['action_type'] == 'deepen'


def test_provider_schema_error_keeps_diagnostics_and_never_retries():
    from unittest.mock import Mock, patch
    from services.gemini_roadmap import generate_roadmap
    client = Mock()
    client.models.generate_content.return_value.text = '{not-valid-json'
    with patch.dict('os.environ', {'GEMINI_API_KEY': 'fake'}), patch('google.genai.Client', return_value=client):
        with pytest.raises(RoadmapValidationError) as caught:
            generate_roadmap(model_input(basis()))
    assert caught.value.detail_code == 'schema_json_invalid'
    client.models.generate_content.assert_called_once()
    client.close.assert_called_once()


def live_fixture(name='live-scope-violation.json'):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures' / 'roadmap-incident' / name).read_text())
    b = basis()
    b.update(skills=fixture['skills'], courses=fixture['courses'], job_status='partial',
             job_summary={'analyzed_jobs': 19, 'failed_jobs': 1})
    b['evidence'] = {s['comparison_ref']: {k: s[k] for k in ('skill_name', 'student_status')} for s in b['skills']}
    return fixture, b


def test_actual_gemini_response_cannot_prescribe_unfocused_pandas_in_python_task():
    fixture, b = live_fixture()
    expected = fixture['expected_failure']
    check(fixture['response'], b, expected['detail_code'], expected['field_path'])


def test_actual_final_gemini_response_passes_without_repair():
    fixture, b = live_fixture('live-valid-v5.json')
    raw = deepcopy(fixture['response'])
    result = validate_result(raw, b)
    assert raw == fixture['response']
    assert result['status'] == 'partial'
    assert result['generation_scope']['included_skills'] == ['Python', 'SQL', 'Tableau', 'Power BI']
    assert sum(len(s['tasks']) for s in result['roadmap']) == 5
    for step in result['roadmap']:
        for target in step['skill_targets']:
            assert target['action_type'] == ('deepen' if target['skill_name'] == 'Python' else 'verify_experience')


@pytest.mark.parametrize('name,prose', [('pandas', 'Pandas로 데이터를 처리한다.'),
                                    ('Excel', 'Excel에서 시각화한다.'),
                                    ('Java', 'Java 코드를 작성한다.')])
def test_unfocused_named_technology_cannot_enter_free_text(name, prose):
    b, raw = basis(), output()
    # Three higher-priority unknowns force this named technology out of focus.
    for i, n in enumerate(('A', 'B', 'D', name)):
        b['skills'].append({'skill_name': n, 'student_status': 'not_verified', 'comparison_ref': f'comparison:{n}'})
        b['evidence'][f'comparison:{n}'] = {'skill_name': n}
    raw['roadmap'][0]['tasks'][0]['action'] = prose
    check(raw, b, 'skill_not_allowed_in_prose', '$.roadmap[0].tasks[0].action')


def test_scope_prose_check_preserves_distinct_products_and_exact_source_quotes():
    b, raw = basis(), output()
    for name in ('JavaScript', 'PostgreSQL', 'C++'):
        b['skills'].append({'skill_name': name, 'student_status': 'confirmed_experience', 'comparison_ref': 'comparison:' + name})
        b['evidence']['comparison:' + name] = {'skill_name': name}
    for name in ('Java', 'C'):
        b['skills'].append({'skill_name': name, 'student_status': 'not_verified', 'job_requirement': {'recommendation_eligible': False}})
    # The name of an excluded skill in a required, exact source quote isn't an activity claim.
    b['courses'][0]['description_text'] = 'Java 소개 및 SQL 데이터 모델'
    raw['recommended_courses'][0]['course_evidence'] = b['courses'][0]['description_text']
    raw['roadmap'][0]['tasks'][0]['action'] = 'JavaScript, PostgreSQL 및 C++ 결과를 기록한다.'
    assert validate_result(raw, b)['status'] == 'success'


def test_wire_schema_explains_bounds_and_verification_fields():
    from services.gemini_jobs import _response_schema
    from services.roadmap_schemas import GeneratedRoadmap
    schema = _response_schema(GeneratedRoadmap.model_json_schema())
    task = schema['$defs']['RoadmapTask']
    assert {'title', 'task_id', 'task_type', 'action', 'completion_criteria', 'deliverable'} == set(task['required'])
    assert '경험' in task['properties']['action']['description'] and '확인' in task['properties']['action']['description']
    assert '1-3' in schema['$defs']['RoadmapStep']['properties']['tasks']['description']
    assert 'out_of_scope_skill_names' in task['properties']['action']['description']

"""No external calls: strict reference/state validation and minimized provider input."""
from copy import deepcopy
from unittest.mock import patch, Mock
import pytest

from services.gemini import GeminiError
from services.gemini_roadmap import generate_roadmap
from services.gemini_jobs import _response_schema
from services.roadmap_schemas import GeneratedRoadmap
from services.roadmap_generation import model_input, validate_result


def basis(status='no_experience', review='confirmed'):
    return {'profile': {'career_goal': '데이터 분석', 'target_role': '데이터 분석가'},
            'skills': [{'skill_name': 'SQL', 'student_status': status, 'comparison_ref': 'comparison:sql'}],
            'evidence': {'comparison:sql': {'skill_name': 'SQL', 'student_status': status}},
            'courses': [{'course_id': 'db', 'course_name': '데이터베이스', 'course_code': 'DB1', 'credits': 3,
                         'is_completed': False, 'description_text': None},
                        {'course_id': 'same-name-completed', 'course_name': '데이터베이스', 'is_completed': True}],
            'review_status': review, 'catalog': {'source_name': 'test', 'completeness_status': 'complete'}, 'job_status': 'success', 'project_status': 'success',
            'limitations': [], 'course_selection_revision': 3, 'reviewed_at': 'now', 'outside_completed_courses': [],
            'job_snapshot_id': 'snapshot', 'job_analyzed_at': 'now', 'job_summary': {'analyzed_jobs': 2},
            'project_version': 'v1', 'project_documents': [], 'excluded_documents': [], 'document_basis': 'hash'}


def output(status='no_experience'):
    intent = 'deepen' if status == 'confirmed_experience' else 'learn' if status == 'no_experience' else 'verify_experience'
    return {'recommended_courses': [{'course_id': 'db', 'related_skills': ['SQL'], 'evidence_refs': ['comparison:sql'],
        'course_evidence': '데이터베이스', 'reason': '데이터 조회 관련 개념', 'personalization_reason': status,
        'course_role': 'foundation', 'recommendation_confidence': 'supported'}],
        'roadmap': [{'step_id': 'step-1', 'order': 1, 'title': 'SQL 활용', 'purpose': '조회 준비', 'reason': status,
            'skill_targets': [{'skill_name': 'SQL', 'student_status': status, 'action_type': intent}],
            'related_course_ids': ['db'], 'depends_on': [], 'evidence_refs': ['comparison:sql'], 'limitations': '제한된 표본',
            'tasks': [{'task_id': 'task-1', 'task_type': 'verify_experience' if intent == 'verify_experience' else 'apply',
                       'title': '조회 기록', 'action': 'SQL 경험 확인 자료를 정리한다.' if intent == 'verify_experience' else '데이터 조회 기록을 정리한다.',
                       'completion_criteria': '기록 파일을 검토할 수 있다.', 'deliverable': '조회 기록 파일'}]}]}


@pytest.mark.parametrize('status,group', [('confirmed_experience', 'confirmed_skills'), ('no_experience', 'learning_candidates'),
    ('not_verified', 'skills_to_verify'), ('document_supported', 'skills_to_verify'), ('needs_confirmation', 'skills_to_verify')])
def test_authoritative_summary_and_intent(status, group):
    result = validate_result(output(status), basis(status))
    assert result['preparation_summary'][group] == ['SQL']
    assert sum(map(len, result['preparation_summary'].values())) == 1


@pytest.mark.parametrize('case', ['foreign_course', 'completed_course', 'duplicate_course', 'made_up_skill', 'foreign_evidence',
    'unrelated_evidence', 'missing_comparison', 'state_changed', 'unknown_treated_as_gap', 'confirmed_basics',
    'cycle', 'missing_step', 'bad_order', 'duplicate_step', 'duplicate_task', 'duplicate_action', 'empty_criterion',
    'empty_action', 'empty_deliverable', 'fake_course_content', 'unselected_course_link', 'invented_schedule',
    'unknown_learning_prose', 'invented_lecture_content', 'frequency_priority'])
def test_invalid_outputs_rejected(case):
    b, raw = basis(), output()
    c, s = raw['recommended_courses'][0], raw['roadmap'][0]
    task = s['tasks'][0]
    if case == 'foreign_course': c['course_id'] = 'not-current-catalog'
    elif case == 'completed_course': c['course_id'] = 'same-name-completed'
    elif case == 'duplicate_course': raw['recommended_courses'].append(deepcopy(c))
    elif case == 'made_up_skill': c['related_skills'] = ['FakeSQL']
    elif case == 'foreign_evidence': s['evidence_refs'].append('experience:another-user')
    elif case == 'unrelated_evidence':
        b['evidence']['job:python'] = {'skill_name': 'Python'}; s['evidence_refs'].append('job:python')
    elif case == 'missing_comparison':
        b['evidence']['job:sql'] = {'skill_name': 'SQL'}; s['evidence_refs'] = ['job:sql']
    elif case == 'state_changed': s['skill_targets'][0]['student_status'] = 'confirmed_experience'
    elif case == 'unknown_treated_as_gap':
        b = basis('not_verified'); s['skill_targets'][0]['student_status'] = 'not_verified'
    elif case == 'confirmed_basics':
        b = basis('confirmed_experience'); s['skill_targets'][0]['student_status'] = 'confirmed_experience'
    elif case in ('cycle', 'missing_step'): s['depends_on'] = ['step-1' if case == 'cycle' else 'step-missing']
    elif case == 'bad_order': s['order'] = 2
    elif case == 'duplicate_step': raw['roadmap'].append(deepcopy(s))
    elif case in ('duplicate_task', 'duplicate_action'):
        copy = deepcopy(task)
        if case == 'duplicate_action': copy['task_id'] = 'task-2'
        s['tasks'].append(copy)
    elif case == 'empty_criterion': task['completion_criteria'] = '  '
    elif case == 'empty_action': task['action'] = ''
    elif case == 'empty_deliverable': task['deliverable'] = ''
    elif case == 'fake_course_content': c['course_evidence'] = '실제 제공되지 않은 실습'
    elif case == 'unselected_course_link': s['related_course_ids'] = ['another-course']
    elif case == 'invented_schedule': s['weeks'] = 3
    elif case == 'unknown_learning_prose':
        b, raw = basis('not_verified'), output('not_verified')
        raw['roadmap'][0]['tasks'][0]['action'] = 'Python 데이터 분석을 실습한다.'
    elif case == 'invented_lecture_content': task['action'] = 'Database 강의를 통해 SQL을 학습한다.'
    elif case == 'frequency_priority': s['reason'] = '공고 빈도가 높으므로 최우선 학습이 필요합니다.'
    with pytest.raises(GeminiError) as error:
        validate_result(raw, b)
    assert error.value.code == 'gemini_invalid_response'


@pytest.mark.parametrize('review', ['confirmed', 'partial', 'unconfirmed'])
def test_course_uncertainty_and_server_fields(review):
    b = basis(review=review)
    result = validate_result(output(), b)['recommended_courses'][0]
    assert result['course_code'] == 'DB1' and result['credits'] == 3
    assert result['description_basis'] == 'name_inference'
    assert result['availability_status'] == 'not_verified'
    assert result['recommendation_confidence'] == 'limited'
    assert result['completion_state'] == ('unconfirmed' if review == 'unconfirmed' else 'not_selected_in_reviewed_catalog')
    b['courses'][0]['description_text'] = 'SQL 조회와 관계형 모델을 학습합니다.'
    raw = output(); raw['recommended_courses'][0]['course_evidence'] = 'SQL 조회'
    course = validate_result(raw, b)['recommended_courses'][0]
    assert course['description_basis'] == 'description'
    assert course['recommendation_confidence'] == ('supported' if review == 'confirmed' else 'limited')


def test_minimal_input_no_reanalysis_or_completed_candidate():
    b = basis(); b['original_document'] = 'do not transmit'; b['session'] = 'private'
    data = model_input(b)
    assert [c['course_id'] for c in data['eligible_courses']] == ['db']
    assert len(data['completed_courses']) == 1
    assert 'original_document' not in data and 'session' not in data
    with patch('services.gemini_roadmap._generate', return_value=output()) as provider:
        generate_roadmap(data)
    assert provider.call_count == 1
    assert provider.call_args.kwargs == {'max_attempts': 1}


def test_actual_transport_429_no_retry():
    class RateLimit(Exception):
        code = 429
    client = Mock(); client.models.generate_content.side_effect = RateLimit()
    with patch.dict('os.environ', {'GEMINI_API_KEY': 'fake', 'GEMINI_MODEL': 'operator-model'}), \
         patch('google.genai.Client', return_value=client), patch('services.gemini_jobs.time.sleep') as sleep:
        with pytest.raises(GeminiError) as error: generate_roadmap(model_input(basis()))
    assert error.value.code == 'gemini_rate_limited'
    client.models.generate_content.assert_called_once()
    assert client.models.generate_content.call_args.kwargs['model'] == 'operator-model'
    sleep.assert_not_called(); client.close.assert_called_once()


def test_wire_schema_keeps_required_fields_named_title():
    schema = _response_schema(GeneratedRoadmap.model_json_schema())
    for name in ('RoadmapStep', 'RoadmapTask'):
        node = schema['$defs'][name]
        assert 'title' in node['required'] and 'title' in node['properties']
        assert set(node['required']).issubset(node['properties'])
        assert 'title' not in node['properties']['title']


def test_generation_focus_prioritizes_user_answers_over_unknown_frequency():
    b = basis()
    unknown = [{'skill_name': f'tool-{i}', 'student_status': 'not_verified', 'comparison_ref': f'comparison:tool-{i}'} for i in range(20)]
    b['skills'] = unknown + b['skills']
    b['evidence'].update({s['comparison_ref']: {'skill_name': s['skill_name']} for s in unknown})
    data = model_input(b)
    assert data['skills'][0]['skill_name'] == 'SQL'
    assert data['skills'][0]['allowed_action_type'] == 'learn'
    assert len(data['skills']) == 4
    assert data['evidence_scope']['verified_skill_count'] == 21

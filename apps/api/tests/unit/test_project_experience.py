"""Source verification and matching never require an external service."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from services import project_experience as service
from services.gemini import GeminiError
from services.gemini_projects import extract_project_experiences
from services.project_experience_schemas import DocumentExperience, ExperienceAnswer


def document(text='제가 Python으로 전처리 코드를 작성했습니다.'):
    return {'document_id': 'doc-1', 'extraction_revision': 2, 'extracted_text': text,
            'segments': [{'start': 0, 'end': len(text), 'page': 2}]}


def extraction(doc, scope='personal', **changes):
    item = {'skill_name': 'Python 3', 'category': 'programming_language', 'activity': '전처리 코드 작성',
            'contribution_scope': scope, 'evidence_text': doc['extracted_text'], **changes}
    return DocumentExperience(document_id=doc['document_id'], extraction_revision=doc['extraction_revision'], experiences=[item])


@pytest.mark.parametrize('scope,text,expected', [
    ('personal', '제가 Python으로 전처리 코드를 작성했습니다.', 'personal'),
    ('team', '팀에서는 Python을 사용했습니다.', 'team'),
    ('unknown', 'Python 라이브러리 목록입니다.', 'unknown'),
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
    ({'role': '프로젝트 리더'}, 'role_or_output_not_in_evidence'),
    ({'output': '우승 프로젝트'}, 'role_or_output_not_in_evidence'),
])
def test_hallucinated_fields_rejected(change, code):
    doc = document()
    verified, errors = service.verify_experiences(doc, extraction(doc, **change), 'analysis')
    assert verified == [] and errors == [{'code': code}]


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
    assert set(json.loads(args['contents'])) == {'document_id', 'extraction_revision', 'extracted_text'}
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

"""Safe diagnostics: never retain model values or Pydantic's input/context text."""
import re

from pydantic import ValidationError

from services.gemini import GeminiError
from services.roadmap_schemas import GeneratedRoadmap

INVALID_MESSAGE = ('생성된 로드맵의 과목·근거·경험 상태 또는 실행 순서를 확인하지 못해 저장하지 않았습니다. '
                   '이전 로드맵과 완료 체크는 유지됩니다. 잠시 후 다시 생성해 주세요. '
                   '반복되면 실행 ID를 알려 주세요.')

# Only schema-owned field names and numeric indexes may enter logs. In particular,
# extra_forbidden locations can contain arbitrary provider/user text.
FIELDS = frozenset({
    'recommended_courses', 'roadmap', 'course_id', 'related_skills', 'evidence_refs',
    'course_evidence', 'reason', 'personalization_reason', 'course_role',
    'recommendation_confidence', 'skill_name', 'student_status', 'action_type',
    'task_id', 'task_type', 'title', 'action', 'completion_criteria', 'deliverable',
    'step_id', 'order', 'purpose', 'skill_targets', 'related_course_ids', 'depends_on',
    'limitations', 'tasks',
})


def field_path(location):
    path = '$'
    for part in location:
        path += f'[{part}]' if isinstance(part, int) else '.' + (part if part in FIELDS else 'unknown_field')
    return path


class RoadmapValidationError(GeminiError):
    def __init__(self, detail_code, location=()):
        super().__init__('gemini_invalid_response', INVALID_MESSAGE)
        self.detail_code = detail_code
        self.field_path = field_path(location)
        self.diagnostic = {'detail_code': self.detail_code, 'field_path': self.field_path}


def invalid(detail_code, location=()):
    raise RoadmapValidationError(detail_code, location) from None


def parse_result(raw, *, from_json=False):
    try:
        if from_json:
            return GeneratedRoadmap.model_validate_json(raw)
        return GeneratedRoadmap.model_validate(raw.model_dump() if isinstance(raw, GeneratedRoadmap) else raw)
    except ValidationError as error:
        first = error.errors(include_input=False, include_context=False, include_url=False)[0]
        kind = first['type']
        code = ('schema_json_invalid' if kind == 'json_invalid' else
                'schema_field_missing' if kind == 'missing' else
                'schema_extra_field' if kind == 'extra_forbidden' else
                'schema_type_invalid' if kind.endswith('_type') else
                'schema_bounds_invalid' if kind in ('too_short', 'too_long', 'string_too_short',
                    'string_too_long', 'greater_than_equal', 'less_than_equal') else 'schema_value_invalid')
        invalid(code, first['loc'])
    except (TypeError, ValueError):
        invalid('schema_type_invalid')


def parse_response(text):
    return parse_result(text, from_json=True)


def stored_error_code(error):
    # Additive encoding in the existing TEXT column, no migration or result changes.
    return f'{error.code}:{error.detail_code}' if isinstance(error, RoadmapValidationError) else error.code


def error_metadata(code):
    if code and re.fullmatch(r'gemini_invalid_response:[a-z_]+', code):
        return {'error_code': 'gemini_invalid_response', 'error_detail_code': code.split(':', 1)[1]}
    return {'error_code': code}

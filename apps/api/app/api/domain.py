from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from services.gemini import GeminiError

COOKIE = 'roadmap_session'
FIELDS = ('career_goal', 'target_role', 'university_id', 'department_id', 'catalog_id', 'year_level', 'earned_credits', 'gpa', 'gpa_scale')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class Problem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def validate(repo, values):
    goal = values['career_goal']
    if not isinstance(goal, str) or not goal.strip():
        raise Problem(422, "validation_error", "목표·관심 분야를 입력해 주세요.")
    if len(goal) > 10000:
        raise Problem(422, 'validation_error', '목표는 10,000자 이하여야 합니다.')
    values['career_goal'] = goal.strip()
    role = values['target_role']
    if role is not None:
        if not isinstance(role, str) or len(role.strip()) > 100:
            raise Problem(422, 'validation_error', '희망 직무는 100자 이하여야 합니다.')
        values['target_role'] = role.strip() or None
    for name in ('university_id', 'department_id', 'catalog_id'):
        if values[name] is not None and (not isinstance(values[name], str) or len(values[name]) > 100):
            raise Problem(422, 'validation_error', '기준 자료 식별자가 올바르지 않습니다.')
    year = values['year_level']
    if year is not None and (type(year) is not int or not 1 <= year <= 4):
        raise Problem(422, 'validation_error', '학년은 1~4 사이여야 합니다.')
    for name, maximum, places in (('earned_credits', Decimal('9999.9'), 1), ('gpa', Decimal('9.99'), 2), ('gpa_scale', Decimal('9.99'), 2)):
        value = values[name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise Problem(422, 'validation_error', '학점과 GPA는 숫자로 입력해 주세요.')
        try:
            n = Decimal(str(value))
            if not n.is_finite() or n < 0 or n > maximum or n != n.quantize(Decimal(1).scaleb(-places)):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise Problem(422, 'validation_error', '학점 또는 GPA의 범위와 소수 자릿수를 확인해 주세요.')
        values[name] = float(n)
    if values['gpa'] is not None and (values['gpa_scale'] is None or values['gpa_scale'] <= 0 or values['gpa'] > values['gpa_scale']):
        raise Problem(422, 'validation_error', 'GPA는 0 이상 만점 이하이며 만점 기준이 필요합니다.')
    if values['gpa_scale'] is not None and values['gpa_scale'] <= 0:
        raise Problem(422, 'validation_error', 'GPA 만점 기준은 0보다 커야 합니다.')
    university, department, catalog = (values[k] for k in ('university_id', 'department_id', 'catalog_id'))
    if university and not repo.university_valid(university):
        raise Problem(422, 'validation_error', '선택할 수 없는 학교입니다.')
    if department and not repo.department_valid(department, university):
        raise Problem(422, 'validation_error', '학과가 선택한 학교에 속하지 않습니다.')
    if catalog and not repo.catalog_valid(catalog, department, values['_existing_catalog']):
        raise Problem(422, 'validation_error', '과목 목록이 선택한 학과에 속하지 않습니다.')


def payload(row):
    status = 'unavailable' if not row['catalog_id'] else 'unconfirmed'
    if row['catalog_id'] and row['reviewed_catalog_id'] == row['catalog_id'] and row['reviewed_selection_revision'] == row['course_selection_revision'] and row['reviewed_at']:
        status = 'partial' if row['reported_missing_courses'] else 'confirmed'
    return {'request_id': row['request_id'], 'input': {key: row[key] for key in FIELDS}, 'input_revision': row['input_revision'], 'selection_revision': row['course_selection_revision'], 'review_status': status, 'updated_at': row['updated_at']}


def json_value(value):
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, datetime): return value.isoformat(timespec='microseconds')
    raise TypeError('Unsupported JSON value')


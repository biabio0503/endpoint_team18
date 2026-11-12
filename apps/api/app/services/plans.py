from decimal import Decimal
from api.dependencies import require_owner, respond
from api.domain import FIELDS, Problem, now, payload, validate
from api.schemas import PlanPatch, validate_body
from config import DB_BACKEND
from services.activity_recommendations import capture_profile


def plan_action(rid, method, body, ctx):
    db, repo, owner = ctx
    require_owner(owner)
    if method == 'PATCH':
        if set(body) != {'expected_input_revision', 'changes'} or type(body['expected_input_revision']) is not int or body['expected_input_revision'] < 0 or not isinstance(body['changes'], dict) or not set(body['changes']).issubset(FIELDS):
            raise Problem(422, 'validation_error', '수정 요청 형식을 확인해 주세요.')
        repo.begin()
    else:
        # Plan revision and recommendation evidence must describe one snapshot.
        db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
    row = repo.plan(rid, owner['owner_id'], lock=method == 'PATCH')
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if method == 'GET':
        result = {**payload(row), 'activity_basis': capture_profile(db, row)[1]}
        repo.commit()
        return respond(200, result)
    if row['input_revision'] != body['expected_input_revision']:
        raise Problem(409, 'revision_conflict', '다른 화면에서 입력이 변경되었습니다. 최신 내용을 불러와 확인해 주세요.')
    values = {field: float(row[field]) if isinstance(row[field], Decimal) else row[field] for field in FIELDS}
    values.update(body['changes'])
    values['_existing_catalog'] = row['catalog_id']
    validate(repo, values)
    validate_body(PlanPatch, body)
    changed = any(values[k] != (float(row[k]) if isinstance(row[k], Decimal) else row[k]) for k in FIELDS)
    scope_changed = any(values[k] != row[k] for k in ('university_id', 'department_id', 'catalog_id'))
    if changed:
        repo.update_plan(rid, FIELDS, values, scope_changed, now())
    result = payload(repo.plan(rid, owner['owner_id']))
    repo.commit()
    return respond(200, result)

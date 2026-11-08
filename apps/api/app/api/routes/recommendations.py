from fastapi import APIRouter, Depends
from api.dependencies import owned_context, parse_body, require_origin, require_owner, respond
from api.domain import Problem, payload
from api.schemas import EmptyRequest, openapi_body, validate_body
from config import DB_BACKEND
from repositories.courses import CourseRepository
from services.course_recommendations import recommend

router = APIRouter(prefix='/api')

@router.post('/roadmap-inputs/{rid:roadmap_id}/course-recommendations', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(EmptyRequest))
def recommendations(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    db, repo, owner = ctx
    require_owner(owner)
    if body != {}: raise Problem(422, 'validation_error', '추천 요청 형식을 확인해 주세요.')
    validate_body(EmptyRequest, body)
    courses_repo = CourseRepository(db)
    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
    row = repo.plan(rid, owner['owner_id'])
    if not row: raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if not row['career_goal'] or not row['career_goal'].strip(): raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    cid = row['catalog_id']
    if not cid or not courses_repo.catalog(cid): raise Problem(422, 'catalog_unavailable', '사용할 과목 목록이 없습니다.')
    courses = courses_repo.courses(rid, cid, include_description=True)
    university = courses_repo.university(row['university_id']) if row['university_id'] else None
    department = courses_repo.department(row['department_id']) if row['department_id'] else None
    profile = {'career_goal': row['career_goal'], 'target_role': row['target_role'], 'university': university['university_name'] if university else None, 'department': department['department_name'] if department else None, 'year_level': row['year_level'], 'review_status': payload(row)['review_status']}
    revision = row['input_revision']
    status = payload(row)['review_status']
    db.commit()
    if not courses:
        return respond(200, {'courses': [], 'status': 'empty_catalog', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal']})
    result = recommend(profile, courses, status)
    # The model call may take time; never return a result for changed input.
    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision or current['catalog_id'] != cid:
        raise Problem(409, 'revision_conflict', '분석 중 입력이 변경되었습니다. 다시 시도해 주세요.')
    latest = {str(c['course_id']): c for c in courses_repo.courses(rid, cid)}
    result = [dict(latest[str(c['course_id'])], is_completed=False, completion_state=c['completion_state']) for c in result if str(c['course_id']) in latest and not latest[str(c['course_id'])]['is_completed']]
    db.commit()
    return respond(200, {'courses': result, 'status': 'ok', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal']})


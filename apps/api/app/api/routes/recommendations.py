from fastapi import APIRouter, Depends
from api.dependencies import owned_context, parse_body, require_origin, require_owner, respond
from api.domain import Problem, payload
from api.schemas import EmptyRequest, openapi_body, validate_body
from config import DB_BACKEND
from repositories.courses import CourseRepository
from services.course_recommendations import recommend, available_courses, RULES_VERSION
from services.ai_guard import guarded_call
from services.project_experience import digest, model_basis, current_comparison

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
    courses = courses_repo.recommendation_courses(rid, cid)
    university = courses_repo.university(row['university_id']) if row['university_id'] else None
    department = courses_repo.department(row['department_id']) if row['department_id'] else None
    profile = {'career_goal': row['career_goal'], 'target_role': row['target_role'], 'university': university['university_name'] if university else None, 'department': department['department_name'] if department else None, 'year_level': row['year_level'], 'review_status': payload(row)['review_status']}
    revision = row['input_revision']
    status = payload(row)['review_status']
    comparison = current_comparison(db, row)
    skills = comparison['comparisons']
    db.commit()
    if not courses:
        return respond(200, {'courses': [], 'status': 'empty_catalog', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal'], 'reason': '현재 과목 목록이 비어 있습니다.'})
    basis = digest([RULES_VERSION, rid, revision, profile, courses, status, skills, model_basis()])
    result = guarded_call(ctx, 'course_recommendations', basis, lambda: recommend(profile, courses, status, skills=skills), units=3, cache=True) if available_courses(courses) else []
    # The model call may take time; never return a result for changed input.
    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision or current['catalog_id'] != cid:
        raise Problem(409, 'revision_conflict', '분석 중 입력이 변경되었습니다. 다시 시도해 주세요.')
    latest = {str(c['course_id']): c for c in courses_repo.recommendation_courses(rid, cid)}
    if digest([RULES_VERSION, rid, revision, profile, list(latest.values()), status, current_comparison(db, current)['comparisons'], model_basis()]) != basis:
        raise Problem(409, 'revision_conflict', '분석 중 과목 근거가 변경되었습니다. 다시 시도해 주세요.')
    # Apply the same completion/equivalence rules even to a cached result.
    result = recommend(profile, list(latest.values()), status, skills=skills)
    db.commit()
    notice = '이수 및 대체과목 제외 후 추천 가능한 과목이 없습니다.' if not result else f'이수 및 대체과목을 제외하면 추천 가능한 고유 과목이 {len(result)}개입니다.' if len(result) < 5 else None
    return respond(200, {'courses': result, 'status': 'ok', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal'], 'reason': notice})


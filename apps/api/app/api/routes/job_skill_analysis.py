"""Owner-scoped job skill analysis of the current saved input (no persistence)."""
from fastapi import APIRouter, Depends
from api.dependencies import owned_context, parse_body, require_origin, respond
from api.domain import Problem
from api.schemas import EmptyRequest, openapi_body, validate_body
from services.job_skill_analysis import analyze_job_skills

router = APIRouter(prefix='/api')


@router.post('/roadmap-inputs/{rid:roadmap_id}/job-skill-analysis',
             dependencies=[Depends(require_origin)], openapi_extra=openapi_body(EmptyRequest))
def job_skill_analysis(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    db, repo, owner = ctx
    if body != {}:
        raise Problem(422, 'validation_error', '분석 요청 형식을 확인해 주세요.')
    validate_body(EmptyRequest, body)
    row = repo.plan(rid, owner['owner_id'])
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if not row['career_goal'] or not row['career_goal'].strip():
        raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    goal, role, revision = row['career_goal'], row['target_role'], row['input_revision']
    db.commit()  # No transaction or lock during either external service call.
    result = analyze_job_skills(goal, role)
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision:
        raise Problem(409, 'revision_conflict', '분석 중 입력이 변경되었습니다. 다시 시도해 주세요.')
    db.commit()
    result['input_revision'] = revision
    return respond(200, result)

"""Owner-scoped, read-only job search using the saved roadmap input."""
from fastapi import APIRouter, Depends, Query
from api.dependencies import owned_context, respond
from api.domain import Problem
from services.himalayas import fetch_jobs

router = APIRouter(prefix='/api')


@router.get('/roadmap-inputs/{rid:roadmap_id}/jobs')
def jobs(rid: str, limit: int = Query(default=20, ge=1, le=100), ctx=Depends(owned_context)):
    db, repo, owner = ctx
    row = repo.plan(rid, owner['owner_id'])
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if not row['career_goal'] or not row['career_goal'].strip():
        raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    goal, role, revision = row['career_goal'], row['target_role'], row['input_revision']
    # Release any read transaction before making network requests.
    db.commit()
    result = fetch_jobs(goal, role, limit)
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision:
        raise Problem(409, 'revision_conflict', '검색 중 입력이 변경되었습니다. 다시 시도해 주세요.')
    result['input_revision'] = revision
    return respond(200, result)

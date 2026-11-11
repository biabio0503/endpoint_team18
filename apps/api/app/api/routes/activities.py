"""Owner-scoped recommendations; public provider receives no student input."""
from fastapi import APIRouter, Depends
from api.dependencies import owned_context, respond
from api.domain import Problem
from services.activity_catalog import catalog
from services.activity_recommendations import capture_profile, recommend

router = APIRouter(prefix='/api')


@router.get('/roadmap-inputs/{rid:roadmap_id}/activities')
def activities(rid: str, ctx=Depends(owned_context)):
    db, repo, owner = ctx
    row = repo.plan(rid, owner['owner_id'])
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if not (row['career_goal'] or '').strip():
        raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    profile, basis = capture_profile(db, row)
    revision = row['input_revision']
    db.commit()  # Never hold a transaction while waiting for the supplier.
    items, sources = catalog.get()
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision or capture_profile(db, current)[1] != basis:
        raise Problem(409, 'revision_conflict', '조회 중 입력이나 경험 근거가 변경되었습니다. 다시 조회해 주세요.')
    return respond(200, {**recommend(profile, items, sources), 'request_id': rid, 'input_revision': revision,
                         'activity_basis': basis})

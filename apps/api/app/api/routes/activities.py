"""Owner-scoped recommendations; public provider receives no student input."""
from fastapi import APIRouter, Depends
from api.dependencies import owned_context, respond
from api.domain import Problem
from repositories.contestkorea import load_catalog as load_contestkorea_catalog
from services.activity_recommendations import capture_profile, recommend
from repositories.dacon import load_catalog

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
    db.commit()
    # Keep verified event witnesses even when a source has expired or has no
    # career keywords. The event-level decision needs both publishers' evidence.
    items, contestkorea_source = load_contestkorea_catalog(db, include_event_context=True)
    dacon_items, dacon_source = load_catalog(db, include_event_context=True)
    items, sources = [*items, *dacon_items], [contestkorea_source, dacon_source]
    current = repo.plan(rid, owner['owner_id'])
    if not current or current['input_revision'] != revision or capture_profile(db, current)[1] != basis:
        raise Problem(409, 'revision_conflict', '조회 중 입력이나 경험 근거가 변경되었습니다. 다시 조회해 주세요.')
    return respond(200, {**recommend(profile, items, sources), 'request_id': rid, 'input_revision': revision,
                         'activity_basis': basis})

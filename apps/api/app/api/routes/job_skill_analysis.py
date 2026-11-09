"""Owner-scoped analysis with reusable server-verified job snapshots."""
from fastapi import APIRouter, Depends
from api.dependencies import owned_context, parse_body, require_origin, respond
from api.domain import Problem
from api.schemas import openapi_body, validate_body
from api.routes.project_experiences import locked_plan
from repositories.experience_analysis import AnalysisRepository
from services.job_skill_analysis import analyze_job_skills
from services.project_experience import job_basis, job_snapshot_payload
from services.project_experience_schemas import JobAnalysisRequest
from services.ai_guard import guarded_call

router = APIRouter(prefix='/api')


@router.post('/roadmap-inputs/{rid:roadmap_id}/job-skill-analysis',
             dependencies=[Depends(require_origin)], openapi_extra=openapi_body(JobAnalysisRequest))
def job_skill_analysis(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    db, repo, owner = ctx
    request = validate_body(JobAnalysisRequest, body)
    row = locked_plan(ctx, rid)
    if not row['career_goal'] or not row['career_goal'].strip():
        raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    goal, role, revision = row['career_goal'], row['target_role'], row['input_revision']
    store = AnalysisRepository(db)
    basis = job_basis(row)
    cached = store.job(rid, basis)
    if cached and not request.refresh:
        result = job_snapshot_payload(cached, revision)
        db.commit()
        return respond(200, result)
    db.commit()  # No transaction or lock during either external service call.
    # Keyword call + at most seven 3..5-job batches, each with at most two attempts.
    result = guarded_call(ctx, 'job_analysis', basis, lambda: analyze_job_skills(goal, role), units=16)
    locked_plan(ctx, rid, revision)
    if result['status'] in ('success', 'partial'):
        # Concurrent first requests keep the winner; explicit refresh may replace it.
        saved = store.job(rid, basis)
        if saved is None or request.refresh:
            saved = store.save_job(rid, basis, revision, result)
        result = {**job_snapshot_payload(saved, revision), 'reused': False}
    elif cached:
        # An explicit retry failing must not destroy already verified evidence.
        result = {**job_snapshot_payload(cached, revision), 'refresh_error': result}
    result['input_revision'] = revision
    db.commit()
    return respond(200, result)

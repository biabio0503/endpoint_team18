"""Persisted, owner-scoped roadmap generation; GET and progress never call AI."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from api.dependencies import owned_context, parse_body, require_origin, respond
from api.domain import Problem
from api.schemas import openapi_body, validate_body
from repositories.roadmaps import RoadmapRepository, metadata, run_payload
from repositories.postgres import StorageConflict
from services.gemini import GeminiError
from services.gemini_roadmap import generate_roadmap
from services.project_experience import digest
from services.roadmap_generation import capture_basis, model_input, validate_result
from services.roadmap_schemas import GenerationRequest, ProgressRequest
from services.ai_guard import guarded_call
from services.limited_roadmap import limited_roadmap

router = APIRouter(prefix='/api/roadmap-inputs/{rid:roadmap_id}', tags=['roadmaps'])


def read_basis(ctx, rid, expected=None, *, serialize=False):
    db, repo, owner = ctx
    postgres = getattr(db, 'backend', 'sqlite') == 'postgres'
    for attempt in range(3):
        try:
            db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ' if postgres else 'BEGIN IMMEDIATE')
            row = repo.plan(rid, owner['owner_id'], lock=True)
            if not row:
                raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
            if expected is not None and row['input_revision'] != expected:
                raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 내용을 불러와 주세요.')
            if postgres and serialize:
                # Advance the MVCC tuple without changing any input/revision/timestamp.
                # A waiting generator must retry its RR snapshot and see the committed lease/cache.
                db.execute('UPDATE roadmap_inputs SET updated_at=updated_at WHERE request_id=?', (rid,))
            return capture_basis(db, row)
        except StorageConflict:
            db.execute('ROLLBACK')
            if attempt == 2:
                raise Problem(409, 'revision_conflict', '입력이 동시에 변경되었습니다. 최신 내용을 다시 불러와 주세요.') from None


def timestamp(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


@router.post('/roadmap', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(GenerationRequest))
def generate(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    request = validate_body(GenerationRequest, body)
    db = ctx[0]
    basis = read_basis(ctx, rid, request.expected_input_revision, serialize=True)
    if not (basis['profile']['career_goal'] or '').strip():
        raise Problem(422, 'goal_required', '진로 목표를 먼저 입력해 주세요.')
    limited = basis['generation_mode'] == 'limited_guidance'
    store = RoadmapRepository(db)
    if not request.refresh or limited:
        cached = store.reusable(rid, digest(basis))
        if cached:
            result = run_payload(store, cached, basis)
            db.commit()
            return respond(200, {**result, 'reused': True})
    store.expire(rid)
    if store.active(rid):
        db.commit()
        raise Problem(409, 'generation_in_progress', '로드맵을 생성 중입니다. 잠시 후 저장 결과를 다시 조회해 주세요.')
    recent = next(iter(store.history(rid)), None)
    if recent and recent['error_code'] == 'gemini_rate_limited' and (datetime.now(timezone.utc) - timestamp(recent['finished_at'])).total_seconds() < 60:
        db.commit()
        raise Problem(503, 'gemini_rate_limited', '사용량 제한 이후 잠시 기다린 뒤 다시 요청해 주세요.')
    run = store.create(rid, basis)
    db.commit()  # No DB transaction/lock while Gemini runs. The unique lease survives across processes.
    try:
        result = limited_roadmap(basis) if limited else guarded_call(ctx, 'roadmap', digest(basis),
            lambda: validate_result(generate_roadmap(model_input(basis)), basis))
    except Exception as error:
        # Do not erase any previous successful run or retain unvalidated provider output.
        current = read_basis(ctx, rid, serialize=True)
        store.fail(rid, run['run_id'], error.code if isinstance(error, (GeminiError, Problem)) else 'generation_failed')
        db.commit()
        if digest(current) != run['basis_hash']:
            raise Problem(409, 'revision_conflict', '생성 중 입력 또는 분석 근거가 변경되었습니다.') from None
        if isinstance(error, (GeminiError, Problem)):
            raise
        raise GeminiError('generation_failed', '로드맵을 생성하지 못했습니다. 이전 저장 결과는 유지됩니다.') from None
    current = read_basis(ctx, rid, serialize=True)
    saved = store.get(rid, run['run_id'])
    if digest(current) != run['basis_hash']:
        store.fail(rid, run['run_id'], 'revision_conflict')
        db.commit()
        raise Problem(409, 'revision_conflict', '생성 중 입력 또는 분석 근거가 변경되었습니다. 최신 기준으로 다시 요청해 주세요.')
    if saved['status'] != 'generating' or timestamp(saved['lease_until']) < datetime.now(timezone.utc):
        store.fail(rid, run['run_id'], 'generation_expired')
        db.commit()
        raise Problem(409, 'generation_expired', '생성 요청의 유효 시간이 지났습니다. 다시 요청해 주세요.')
    saved = store.finish(rid, run['run_id'], result)
    result = run_payload(store, saved, current)
    db.commit()
    return respond(201, {**result, 'reused': False})


@router.get('/roadmap')
def latest(rid: str, ctx=Depends(owned_context)):
    current = read_basis(ctx, rid)
    store = RoadmapRepository(ctx[0])
    run = store.reusable(rid, digest(current))
    history = store.history(rid)
    run = run or next((r for r in history if r['status'] in ('success', 'partial')), None) or next(iter(history), None)
    result = run_payload(store, run, current) if run else {
        'status': 'not_started', 'limited_guidance_available': current['generation_mode'] == 'limited_guidance',
        'input_revision': current['input_revision'], 'current_input_revision': current['input_revision']}
    ctx[0].commit()
    return respond(200, result)


@router.get('/roadmaps')
def history(rid: str, ctx=Depends(owned_context)):
    current = read_basis(ctx, rid)
    result = {'runs': [metadata(r, current) for r in RoadmapRepository(ctx[0]).history(rid)], 'input_revision': current['input_revision']}
    ctx[0].commit()
    return respond(200, result)


@router.get('/roadmaps/{run_id:roadmap_id}')
def detail(rid: str, run_id: str, ctx=Depends(owned_context)):
    current = read_basis(ctx, rid)
    store = RoadmapRepository(ctx[0])
    run = store.get(rid, run_id)
    if not run:
        raise Problem(404, 'not_found', '로드맵 실행 이력을 찾을 수 없습니다.')
    result = run_payload(store, run, current)
    ctx[0].commit()
    return respond(200, result)


@router.patch('/roadmaps/{run_id:roadmap_id}/tasks/{task_id}', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(ProgressRequest))
def progress(rid: str, run_id: str, task_id: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    request = validate_body(ProgressRequest, body)
    current = read_basis(ctx, rid, serialize=True)
    store = RoadmapRepository(ctx[0])
    run = store.get(rid, run_id)
    if not run:
        raise Problem(404, 'not_found', '로드맵 실행 이력을 찾을 수 없습니다.')
    if metadata(run, current)['details_restricted']:
        raise Problem(409, 'evidence_unavailable', '문서 기준이 변경된 결과는 상세 조회 및 진행 체크를 할 수 없습니다.')
    tasks = store.progress(run_id) if run['status'] in ('success', 'partial') else {}
    if task_id not in tasks:
        raise Problem(404, 'not_found', '실행 항목을 찾을 수 없습니다.')
    if not store.update_progress(run_id, task_id, request.is_completed, request.expected_progress_version):
        raise Problem(409, 'progress_conflict', '다른 화면에서 진행 상태를 변경했습니다. 저장 상태를 다시 불러와 주세요.')
    result = run_payload(store, run, current)
    ctx[0].commit()
    return respond(200, result)

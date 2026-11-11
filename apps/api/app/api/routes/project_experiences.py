"""Version-bound project analysis/answers and read-only comparison of server snapshots."""
from fastapi import APIRouter, Depends

from api.dependencies import owned_context, parse_body, require_origin, respond
from api.domain import Problem, now
from api.schemas import openapi_body, validate_body
from repositories.documents import DocumentRepository
from repositories.experience_analysis import AnalysisRepository, decode
from services.project_experience import (analyze_document, current_project, current_comparison,
    documents_for_analysis, current_job_snapshot, project_version, skill_key, snapshot_skill_key)
from services.project_experience_schemas import ExperienceAnswer, SkillAnswer, ProjectAnalysisRequest
from services.ai_guard import guarded_call

router = APIRouter(prefix='/api/roadmap-inputs/{rid:roadmap_id}', tags=['project-experiences'])


def locked_plan(ctx, rid, expected=None):
    db, repo, owner = ctx
    repo.begin()
    row = repo.plan(rid, owner['owner_id'], lock=True)
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if expected is not None and row['input_revision'] != expected:
        raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 내용을 불러와 다시 확인해 주세요.')
    return row


@router.get('/project-experience-analysis')
def get_analysis(rid: str, ctx=Depends(owned_context)):
    row = locked_plan(ctx, rid)
    result = current_project(ctx[0], rid, row['input_revision'])
    ctx[0].commit()
    return respond(200, result)


@router.post('/project-experience-analysis', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(ProjectAnalysisRequest))
def run_analysis(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    request = validate_body(ProjectAnalysisRequest, body)
    db, repo, owner = ctx
    row = locked_plan(ctx, rid, request.expected_input_revision)
    documents, _, basis = documents_for_analysis(db, rid)
    store = AnalysisRepository(db)
    version = project_version()
    saved = store.analyses(rid, version)
    pending = [d for d in documents if request.refresh or (d['document_id'], d['extraction_revision']) not in saved or
               decode(saved[(d['document_id'], d['extraction_revision'])]['result_json'])['status'] not in ('success', 'partial')]
    db.commit()  # External calls never hold database locks.
    def analyze_pending():
        results = []
        for document in pending:
            result = analyze_document(document)
            results.append((document, result))
            if any(e['code'] == 'gemini_rate_limited' for e in result['errors']):
                break
        return results
    results = guarded_call(ctx, 'project_analysis', basis, analyze_pending, units=2 * len(pending)) if pending else []
    row = locked_plan(ctx, rid, request.expected_input_revision)
    if documents_for_analysis(db, rid)[2] != basis:
        raise Problem(409, 'revision_conflict', '분석 중 문서가 변경되었습니다. 다시 시도해 주세요.')
    refresh_errors = []
    for document, result in results:
        previous = saved.get((document['document_id'], document['extraction_revision']))
        if request.refresh and previous and result['status'] == 'error':
            refresh_errors.extend({**e, 'document_id': document['document_id']} for e in result['errors'])
            continue  # Keep verified results and their answers after a failed refresh.
        store.save_document(rid, document, version, row['input_revision'], result,
                            replace_analysis_id=previous['analysis_id'] if request.refresh and previous else None)
    result = current_project(db, rid, row['input_revision'])
    result['requested_documents'] = len(results)
    result['reused_documents'] = len(documents) - len(pending)
    result['refresh_errors'] = refresh_errors
    db.commit()
    return respond(200, result)


@router.patch('/project-experiences/{eid:roadmap_id}/confirmation', dependencies=[Depends(require_origin)],
              openapi_extra=openapi_body(ExperienceAnswer))
def confirm_experience(rid: str, eid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    answer = validate_body(ExperienceAnswer, body)
    db, _, _ = ctx
    row = locked_plan(ctx, rid, answer.expected_input_revision)
    result = current_project(db, rid, row['input_revision'])
    item = next((e for e in result['experiences'] if e['experience_id'] == eid), None)
    if item is None:
        raise Problem(409, 'evidence_unavailable', '현재 문서 버전에서 유효한 분석 항목이 아닙니다. 다시 불러와 주세요.')
    user = item['user_answer']
    correction = answer.correction.model_dump() if answer.correction else None
    if not user or user['status'] != answer.status or user['correction'] != correction:
        revision = row['input_revision'] + 1
        AnalysisRepository(db).save_answer(item, answer, revision)
        DocumentRepository(db).bump_input(rid, now())
    else:
        revision = row['input_revision']
    result = current_project(db, rid, revision)
    db.commit()
    return respond(200, result)


@router.get('/skill-comparison')
def get_comparison(rid: str, ctx=Depends(owned_context)):
    row = locked_plan(ctx, rid)
    result = current_comparison(ctx[0], row)
    ctx[0].commit()
    return respond(200, result)


@router.post('/skill-comparison/answers', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(SkillAnswer))
def answer_skill(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    answer = validate_body(SkillAnswer, body)
    db, repo, owner = ctx
    row = locked_plan(ctx, rid, answer.expected_input_revision)
    store = AnalysisRepository(db)
    snapshot = current_job_snapshot(store, row)
    if not snapshot or snapshot['snapshot_id'] != answer.snapshot_id:
        raise Problem(409, 'revision_conflict', '직무 분석 기준이 변경되었습니다. 다시 불러와 주세요.')
    jobs = decode(snapshot['result_json'])
    exact = next((s for s in jobs['skills'] if s['name'] == answer.skill_name), None)
    matched = exact or next((s for s in jobs['skills'] if skill_key(s['name']) == skill_key(answer.skill_name)), None)
    if matched is None:
        raise Problem(422, 'validation_error', '분석된 직무 기술에 대한 답변만 저장할 수 있습니다.')
    key = snapshot_skill_key(jobs, matched['name'])
    basis = documents_for_analysis(db, rid)[2]
    previous = store.skill_answers(snapshot['snapshot_id'], basis).get(key)
    if not previous or previous['status'] != answer.status:
        store.save_skill_answer(snapshot['snapshot_id'], basis, key, answer.status, row['input_revision'] + 1)
        DocumentRepository(db).bump_input(rid, now())
    result = current_comparison(db, repo.plan(rid, owner['owner_id']))
    db.commit()
    return respond(200, result)

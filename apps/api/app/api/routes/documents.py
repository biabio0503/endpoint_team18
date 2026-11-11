"""Document routes for SQLite and the opt-in PostgreSQL deployment."""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from starlette.datastructures import UploadFile
from api.dependencies import get_context, parse_body, require_origin, require_owner, respond
from api.domain import Problem
from api.schemas import RevisionRequest, validate_body, openapi_body
from config import DB_BACKEND, MAX_DOCUMENT_BYTES, MAX_DOCUMENTS
from providers.document_storage import get_storage
from providers.document_parser import validate_file, InvalidDocument
from repositories.documents import DocumentRepository
from services.document_ocr import policy as ocr_policy, retry_policy
from providers.google_vision_ocr import MESSAGES as OCR_MESSAGES
from worker.documents import timestamp, later, request_work

router = APIRouter(prefix='/api/roadmap-inputs/{rid:roadmap_id}/documents', tags=['documents'])


def document_context(rid: str, ctx=Depends(get_context)):
    if DB_BACKEND == 'postgres' and os.environ.get('ROADMAP_POSTGRES_DOCUMENTS_ENABLED') != '1':
        raise Problem(503, 'feature_unavailable', 'PostgreSQL 문서 기능은 아직 연결되지 않았습니다.')
    require_owner(ctx[2])
    plan(ctx[1], ctx[2], rid)
    return ctx


def plan(repo, owner, rid, lock=False):
    row = repo.plan(rid, owner['owner_id'], lock=lock)
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    return row


def document(documents, rid, did):
    doc = documents.get(rid, did)
    if not doc: raise Problem(404, 'not_found', '문서를 찾을 수 없습니다.')
    if doc['removed_at']: raise Problem(410, 'removed', '삭제된 문서입니다.')
    return doc


def summary(row):
    eligible = row['extraction_status'] == 'ready' or (row['extraction_status'] == 'partial' and row['partial_confirmed_at'] is not None)
    return {k: row[k] for k in ('document_id','original_filename','mime_type','file_size_bytes','extraction_status','extraction_revision','extraction_error_code','partial_confirmed_at','created_at')} | {'analysis_eligible': eligible}


def check_revision(body, row):
    if set(body) != {'expected_input_revision'} or type(body.get('expected_input_revision')) is not int or body['expected_input_revision'] < 0:
        raise Problem(422, 'validation_error', '입력 버전을 확인해 주세요.')
    validate_body(RevisionRequest, body)
    if body['expected_input_revision'] != row['input_revision']:
        raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')


async def upload_data(request: Request):
    try:
        size = int(request.headers.get('content-length', '0'))
        if size <= 0 or size > MAX_DOCUMENT_BYTES + 65536:
            raise Problem(413, 'too_large', '파일 크기 제한을 초과했습니다.')
        if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
            raise ValueError
        # Content-Length is untrusted. Bound the multipart envelope before
        # Starlette parses or spools any uploaded files.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_DOCUMENT_BYTES + 65536:
                raise Problem(413, 'too_large', '파일 크기 제한을 초과했습니다.')
        request._body = bytes(raw)
        async with request.form(max_files=1, max_fields=1) as form:
            fields = list(form.multi_items())
            if len(fields) != 2 or {key for key, _ in fields} != {'file', 'expected_input_revision'}:
                raise ValueError
            uploaded = form['file']
            revision = form['expected_input_revision']
            if not isinstance(uploaded, UploadFile) or not isinstance(revision, str) or not re.fullmatch(r'0|[1-9][0-9]*', revision.strip()):
                raise ValueError
            data = await uploaded.read(MAX_DOCUMENT_BYTES + 1)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise Problem(413, 'too_large', '파일 크기 제한을 초과했습니다.')
            _, mime = validate_file(uploaded.filename, data)
            return uploaded.filename, data, mime, int(revision.strip())
    except Problem:
        raise
    except InvalidDocument as error:
        raise Problem(422, 'invalid_file', str(error)) from error
    except Exception:
        raise Problem(400, 'invalid_multipart', '파일 업로드 요청 형식을 확인해 주세요.') from None


@router.get('')
def list_documents(rid: str, background: BackgroundTasks, ctx=Depends(document_context)):
    db, repo, owner = ctx
    plan(repo, owner, rid)
    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ' if DB_BACKEND == 'postgres' else 'BEGIN'); row = plan(repo, owner, rid)
    ocr = ocr_policy(db)
    docs = []
    for d in DocumentRepository(db).list_active(rid):
        retry = retry_policy(d, ocr, db)
        docs.append(summary(d) | retry | {'retry_message': OCR_MESSAGES.get(retry['retry_reason'])})
    db.commit()
    if DB_BACKEND == 'postgres': background.add_task(request_work)
    return respond(200, {'documents': docs, 'input_revision': row['input_revision'], 'analysis_eligible': any(d['analysis_eligible'] for d in docs), 'ocr': ocr | {'message': OCR_MESSAGES.get(ocr['reason'])}, 'upload_policy': {'max_files': MAX_DOCUMENTS, 'max_file_bytes': MAX_DOCUMENT_BYTES, 'extensions': ['pdf','docx','txt']}})


@router.post('', dependencies=[Depends(require_origin)], status_code=201, openapi_extra={'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {'type': 'object', 'required': ['file', 'expected_input_revision'], 'properties': {'file': {'type': 'string', 'format': 'binary'}, 'expected_input_revision': {'type': 'integer', 'minimum': 0}}}}}}})
def upload(rid: str, background: BackgroundTasks, ctx=Depends(document_context), file=Depends(upload_data)):
    db, repo, owner = ctx
    plan(repo, owner, rid)
    filename, data, mime, expected = file
    documents = DocumentRepository(db)
    key = str(uuid.uuid4()); store = get_storage(); saved = False
    if DB_BACKEND == 'postgres':
        # The reservation survives an interrupted request or an ambiguous
        # Storage/DB response. A later worker removes only this exact key.
        repo.begin(); row = plan(repo, owner, rid, lock=True)
        if expected != row['input_revision']: raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')
        t = timestamp()
        if documents.count_active(rid) + documents.count_uploading(rid, t) >= MAX_DOCUMENTS:
            raise Problem(422, 'file_limit', '등록 가능한 문서 개수를 초과했습니다.')
        documents.reserve_upload(key, rid, t, later(900)); db.commit()
        store.save(key, data, mime)
        repo.begin(); row = plan(repo, owner, rid, lock=True)
        reservation = documents.lock_reservation(key, rid)
        if not reservation or reservation['expires_at'] <= datetime.now(timezone.utc):
            raise Problem(409, 'upload_expired', '업로드 시간이 만료되었습니다. 다시 시도해 주세요.')
        if expected != row['input_revision']:
            raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')
        t = timestamp(); documents.create(key, rid, filename, mime, len(data), t)
        documents.bump_input(rid, t); documents.finish_reservation(key, t)
        result = summary(documents.get(rid, key)); db.commit()
        background.add_task(request_work)
        return respond(201, {'document': result, 'input_revision': row['input_revision'] + 1})
    try:
        db.execute('BEGIN IMMEDIATE'); row = plan(repo, owner, rid)
        if expected != row['input_revision']: raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 문서 상태를 불러와 주세요.')
        if documents.count_active(rid) >= MAX_DOCUMENTS: raise Problem(422, 'file_limit', '등록 가능한 문서 개수를 초과했습니다.')
        store.save(key, data); saved = True; t = timestamp()
        documents.create(key, rid, filename, mime, len(data), t)
        documents.bump_input(rid, t)
        result = summary(documents.get(rid, key)); db.commit()
    except Exception:
        if saved: store.delete(key)
        raise
    return respond(201, {'document': result, 'input_revision': row['input_revision'] + 1})


@router.get('/{did:roadmap_id}/extractions/{revision:int}')
def extraction(rid: str, did: str, revision: int, ctx=Depends(document_context)):
    db, repo, owner = ctx
    plan(repo, owner, rid); documents = DocumentRepository(db); doc = document(documents, rid, did)
    item = documents.extraction(did, revision)
    if not item: raise Problem(404, 'not_found', '추출 버전을 찾을 수 없습니다.')
    decode = lambda value: json.loads(value) if isinstance(value, str) else value
    return respond(200, {'document_id': did, 'extraction_revision': item['extraction_revision'], 'extracted_text': item['extracted_text'], 'segments': decode(item['segments']), 'limitations': decode(item['limitations']), 'extraction_status': item['extraction_status'], 'is_current_revision': doc['extraction_revision'] == item['extraction_revision'], 'partial_confirmed': bool(doc['partial_confirmed_at']) and doc['extraction_revision'] == item['extraction_revision']})


def mutate(rid, did, action, revision, body, ctx):
    db, repo, owner = ctx
    plan(repo, owner, rid); documents = DocumentRepository(db); document(documents, rid, did)
    repo.begin(); row = plan(repo, owner, rid, lock=True); doc = document(documents, rid, did)
    check_revision(body, row); t = timestamp()
    if action == 'delete':
        documents.remove(did, t); documents.bump_input(rid, t); db.commit()
        return respond(200, {'document_id': did, 'cleanup_status': 'queued', 'input_revision': row['input_revision'] + 1})
    if action == 'retry':
        if doc['extraction_status'] == 'pending': raise Problem(409, 'already_pending', '이미 문서를 읽고 있습니다.')
        retry = retry_policy(doc, ocr_policy(db), db)
        if not retry['retry_available']:
            code = retry['retry_reason']
            raise Problem(429 if code == 'ocr_budget_exceeded' else 422, code,
                          OCR_MESSAGES.get(code, '현재 다시 읽을 수 없습니다.'))
        new_rev = doc['extraction_revision'] + 1
        documents.retry(did, new_rev, t); documents.bump_input(rid, t); db.commit()
        return respond(202, {'document_id': did, 'extraction_revision': new_rev, 'extraction_status': 'pending', 'input_revision': row['input_revision'] + 1})
    if revision != doc['extraction_revision']: raise Problem(409, 'revision_conflict', '문서 추출 버전이 변경되었습니다.')
    if doc['extraction_status'] != 'partial': raise Problem(422, 'not_partial', '일부 추출 문서만 확인할 수 있습니다.')
    item = documents.extraction(did, revision)
    if not item or not item['extracted_text'] or not item['extracted_text'].strip(): raise Problem(422, 'empty_text', '확인할 본문이 없습니다.')
    if not doc['partial_confirmed_at']:
        documents.confirm(did, t); documents.bump_input(rid, t); new_input = row['input_revision'] + 1
    else:
        t = doc['partial_confirmed_at']; new_input = row['input_revision']
    db.commit()
    return respond(200, {'partial_confirmed_at': t, 'analysis_eligible': True, 'input_revision': new_input})


@router.delete('/{did:roadmap_id}', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(RevisionRequest))
def delete_document(rid: str, did: str, background: BackgroundTasks, ctx=Depends(document_context), body=Depends(parse_body)):
    result = mutate(rid, did, 'delete', None, body, ctx)
    if DB_BACKEND == 'postgres': background.add_task(request_work)
    return result


@router.post('/{did:roadmap_id}/retry-extraction', dependencies=[Depends(require_origin)], status_code=202, openapi_extra=openapi_body(RevisionRequest))
def retry(rid: str, did: str, background: BackgroundTasks, ctx=Depends(document_context), body=Depends(parse_body)):
    result = mutate(rid, did, 'retry', None, body, ctx)
    if DB_BACKEND == 'postgres': background.add_task(request_work)
    return result


@router.post('/{did:roadmap_id}/extractions/{revision:int}/confirmation', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(RevisionRequest))
def confirm(rid: str, did: str, revision: int, ctx=Depends(document_context), body=Depends(parse_body)):
    return mutate(rid, did, 'confirm', revision, body, ctx)

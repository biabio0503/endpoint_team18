from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import secrets
import uuid
from fastapi import APIRouter, Depends, Request
from api.dependencies import get_context, require_origin, respond, parse_body, require_owner, owned_context
from api.domain import Problem, FIELDS, now, payload, validate
from api.schemas import validate_body, PlanPatch, SelectionPatch, ReviewRequest, EmptyRequest, openapi_body
from config import DB_BACKEND, SECURE_COOKIE
from repositories.p2 import CourseRepository
from services.course_recommendations import recommend

router = APIRouter(prefix='/api')

@router.get('/reference')
def reference(ctx=Depends(get_context)):
    db, repo, owner = ctx
    return respond(200, repo.reference())

@router.get('/universities')
def universities(ctx=Depends(get_context)):
    db, repo, owner = ctx
    return respond(200, {'universities': CourseRepository(db).universities()})

@router.get('/universities/{university_id}/departments')
def departments(university_id: str, ctx=Depends(get_context)):
    db, repo, owner = ctx
    courses_repo = CourseRepository(db)
    university = courses_repo.university(university_id)
    if not university: raise Problem(404, 'not_found', '학교를 찾을 수 없습니다.')
    return respond(200, {'departments': courses_repo.departments(university_id)})

@router.get('/departments/{department_id}/catalogs')
def catalogs(department_id: str, ctx=Depends(get_context)):
    db, repo, owner = ctx
    courses_repo = CourseRepository(db)
    department = courses_repo.department(department_id)
    if not department: raise Problem(404, 'not_found', '학과를 찾을 수 없습니다.')
    catalogs = courses_repo.catalogs(department_id)
    support = 'unsupported' if not department['is_supported'] else 'supported' if catalogs else 'no_catalog'
    return respond(200, {'catalogs': catalogs, 'support_status': support})

@router.post('/roadmap-inputs', dependencies=[Depends(require_origin)], status_code=201)
def create_plan(ctx=Depends(get_context)):
    db, repo, owner = ctx
    repo.begin()
    cookie = None
    if owner is None:
        token = secrets.token_urlsafe(32)
        owner_id = str(uuid.uuid4())
        created = now()
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec='microseconds')
        repo.add_owner(owner_id, sha256(token.encode()).hexdigest(), expires, created)
        cookie = token
    else:
        owner_id = owner['owner_id']
    request_id, created = str(uuid.uuid4()), now()
    repo.create_plan(request_id, owner_id, created)
    row = repo.plan(request_id, owner_id)
    repo.commit()
    return respond(201, payload(row), cookie)

@router.get('/roadmap-inputs/resume')
def resume(ctx=Depends(get_context)):
    db, repo, owner = ctx
    row = repo.resume(owner['owner_id']) if owner else None
    return respond(200, {'found': bool(row), 'request': dict(row) if row else None})

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

@router.get('/roadmap-inputs/{rid:roadmap_id}/courses')
def courses(rid: str, request: Request, ctx=Depends(owned_context)):
    return course_action(rid, 'courses', 'GET', request, None, ctx)

@router.patch('/roadmap-inputs/{rid:roadmap_id}/course-selections', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(SelectionPatch))
def selections(rid: str, request: Request, ctx=Depends(owned_context), body=Depends(parse_body)):
    require_owner(ctx[2])
    return course_action(rid, 'course-selections', 'PATCH', request, body, ctx)

@router.post('/roadmap-inputs/{rid:roadmap_id}/course-selection-review', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(ReviewRequest))
def review(rid: str, request: Request, ctx=Depends(owned_context), body=Depends(parse_body)):
    require_owner(ctx[2])
    return course_action(rid, 'course-selection-review', 'POST', request, body, ctx)

def course_action(rid, action, method, request, body, ctx):
    db, repo, owner = ctx
    require_owner(owner)
    courses_repo = CourseRepository(db)
    # Read the entire listing from one snapshot; serialize all writes to the parent row.
    if method == 'GET': db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
    else: repo.begin()
    row = repo.plan(rid, owner['owner_id'], lock=method != 'GET')
    if not row: raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if method == 'GET':
        query = {key: request.query_params.getlist(key) for key in request.query_params}
        allowed = {'catalog_id', 'q', 'year', 'category', 'completed_only', 'page', 'page_size'}
        if not set(query).issubset(allowed) or any(len(v) != 1 for v in query.values()):
            raise Problem(422, 'validation_error', '조회 조건을 확인해 주세요.')
        q = {k:v[0] for k,v in query.items()}
        cid = q.get('catalog_id')
        if not cid: raise Problem(422, 'validation_error', '과목 목록 기준이 필요합니다.')
        if cid != row['catalog_id']: raise Problem(409, 'catalog_conflict', '저장된 과목 목록 기준이 변경되었습니다.')
        catalog = courses_repo.catalog(cid)
        if not catalog: raise Problem(422, 'unavailable', '과목 목록을 사용할 수 없습니다.')
        try:
            page, size = int(q.get('page', '1')), int(q.get('page_size', '20'))
            year = int(q['year']) if q.get('year') else None
            if page < 1 or size < 1 or size > 100 or (year is not None and not 1 <= year <= 4) or q.get('completed_only','false') not in ('true','false') or len(q.get('q','')) > 100 or len(q.get('category','')) > 100: raise ValueError
        except ValueError: raise Problem(422, 'validation_error', '검색 또는 페이지 조건이 올바르지 않습니다.')
        status = payload(row)['review_status']
        all_courses = courses_repo.courses(rid, cid)
        for course in all_courses:
            course['is_completed'] = bool(course['is_completed'])
            course['completion_state'] = 'self_reported_completed' if course['is_completed'] else 'not_selected_in_reviewed_catalog' if status in ('confirmed', 'partial') else 'unconfirmed'
        selected = [c for c in all_courses if c['is_completed']]
        search = q.get('q','').strip().casefold()
        filtered = [c for c in all_courses if (not search or search in c['course_name'].casefold() or search in (c['course_code'] or '').casefold()) and (year is None or c['recommended_year'] == year) and (not q.get('category') or c['category'] == q['category']) and (q.get('completed_only') != 'true' or c['is_completed'])]
        categories = sorted({c['category'] for c in all_courses if c['category']})
        result = {'catalog_id':cid, 'catalog_version':catalog['version_label'], 'scope_description':catalog['scope_description'], 'completeness_status':catalog['completeness_status'], 'source':{'name':catalog['source_name'],'url':catalog['source_url'],'retrieved_at':catalog['retrieved_at']}, 'selection_revision':row['course_selection_revision'], 'input_revision':row['input_revision'], 'review_status':status, 'reported_missing_courses':bool(row['reported_missing_courses']) if status in ('confirmed','partial') else False, 'reviewed_at':row['reviewed_at'] if status in ('confirmed','partial') else None, 'courses':filtered[(page-1)*size:page*size], 'selected_courses':selected, 'selection_summary':{'count':len(selected), 'known_credits':float(sum(Decimal(str(c['credits'])) for c in selected if c['credits'] is not None)), 'unknown_credits_count':sum(c['credits'] is None for c in selected)}, 'out_of_scope_completed_courses':courses_repo.outside(rid,cid), 'categories':categories, 'page':page, 'page_size':size, 'total':len(filtered)}
        db.commit()
        return respond(200,result)
    cid = body.get('catalog_id')
    if not isinstance(cid, str) or not cid: raise Problem(422, 'validation_error', '과목 목록 기준이 필요합니다.')
    if cid != row['catalog_id']: raise Problem(409, 'catalog_conflict', '저장된 과목 목록 기준이 변경되었습니다.')
    catalog = courses_repo.catalog(cid)
    if not catalog: raise Problem(422, 'unavailable', '과목 목록을 사용할 수 없습니다.')
    rev = body.get('expected_selection_revision')
    if type(rev) is not int or rev < 0: raise Problem(422, 'validation_error', '선택 버전을 확인해 주세요.')
    if rev != row['course_selection_revision']: raise Problem(409, 'revision_conflict', '과목 선택이 변경되었습니다. 최신 내용을 불러와 주세요.')
    if action == 'course-selections':
        changes = body.get('changes')
        if set(body) != {'catalog_id','expected_selection_revision','changes'} or not isinstance(changes,list) or not changes or len(changes)>100:
            raise Problem(422, 'validation_error', '과목 선택 요청을 확인해 주세요.')
        seen=set(); pending=[]
        for change in changes:
            if not isinstance(change,dict) or set(change) != {'course_id','is_completed'} or not isinstance(change['course_id'],str) or type(change['is_completed']) is not bool or change['course_id'] in seen:
                raise Problem(422, 'validation_error', '중복 또는 잘못된 과목 선택입니다.')
            course_id, target = change['course_id'], change['is_completed']; seen.add(course_id)
            old = courses_repo.state(rid,course_id)
            inside = courses_repo.membership(cid,course_id)
            if not inside and not (old and old['is_completed'] and not target):
                raise Problem(422, 'validation_error', '현재 목록에 없는 과목입니다.')
            previous = bool(old['is_completed']) if old else False
            if previous != target: pending.append((course_id, cid if inside else old['source_catalog_id'], target))
        validate_body(SelectionPatch, body)
        if pending:
            at=now()
            for course_id, source_id, target in pending: courses_repo.save_state(rid,course_id,source_id,target,at)
            courses_repo.changed(rid,at)
        row=repo.plan(rid,owner['owner_id']); repo.commit()
        return respond(200, {'selection_revision':row['course_selection_revision'],'input_revision':row['input_revision'],'review_status':payload(row)['review_status'],'saved_changes':changes})
    if set(body) != {'catalog_id','expected_selection_revision','expected_input_revision','reported_missing_courses'} or type(body.get('expected_input_revision')) is not int or body['expected_input_revision'] < 0 or type(body.get('reported_missing_courses')) is not bool:
        raise Problem(422, 'validation_error', '확인 요청을 확인해 주세요.')
    validate_body(ReviewRequest, body)
    if body['expected_input_revision'] != row['input_revision']: raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 내용을 불러와 주세요.')
    status = payload(row)['review_status']; missing=body['reported_missing_courses']
    if status not in ('confirmed','partial') or bool(row['reported_missing_courses']) != missing:
        courses_repo.review(rid,cid,rev,missing,now())
    row=repo.plan(rid,owner['owner_id']); repo.commit()
    return respond(200, {'review_status':payload(row)['review_status'],'reviewed_catalog_id':row['reviewed_catalog_id'],'reviewed_selection_revision':row['reviewed_selection_revision'],'reviewed_at':row['reviewed_at'],'input_revision':row['input_revision'],'selection_revision':row['course_selection_revision']})

@router.get('/roadmap-inputs/{rid:roadmap_id}')
def get_plan(rid: str, ctx=Depends(owned_context)):
    return plan_action(rid, 'GET', None, ctx)

@router.patch('/roadmap-inputs/{rid:roadmap_id}', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(PlanPatch))
def patch_plan(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    require_owner(ctx[2])
    return plan_action(rid, 'PATCH', body, ctx)

def plan_action(rid, method, body, ctx):
    db, repo, owner = ctx
    require_owner(owner)
    if method == 'PATCH':
        if set(body) != {'expected_input_revision', 'changes'} or type(body['expected_input_revision']) is not int or body['expected_input_revision'] < 0 or not isinstance(body['changes'], dict) or not set(body['changes']).issubset(FIELDS):
            raise Problem(422, 'validation_error', '수정 요청 형식을 확인해 주세요.')
        repo.begin()
    row = repo.plan(rid, owner['owner_id'], lock=method == 'PATCH')
    if not row:
        raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
    if method == 'GET':
        return respond(200, payload(row))
    if row['input_revision'] != body['expected_input_revision']:
        raise Problem(409, 'revision_conflict', '다른 화면에서 입력이 변경되었습니다. 최신 내용을 불러와 확인해 주세요.')
    values = {field: float(row[field]) if isinstance(row[field], Decimal) else row[field] for field in FIELDS}
    values.update(body['changes'])
    values['_existing_catalog'] = row['catalog_id']
    validate(repo, values)
    validate_body(PlanPatch, body)
    changed = any(values[k] != (float(row[k]) if isinstance(row[k], Decimal) else row[k]) for k in FIELDS)
    scope_changed = any(values[k] != row[k] for k in ('university_id', 'department_id', 'catalog_id'))
    if changed:
        repo.update_plan(rid, FIELDS, values, scope_changed, now())
    result = payload(repo.plan(rid, owner['owner_id']))
    repo.commit()
    return respond(200, result)

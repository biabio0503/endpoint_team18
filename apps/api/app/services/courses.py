from decimal import Decimal
from api.dependencies import require_owner, respond
from api.domain import Problem, now, payload
from api.schemas import ReviewRequest, SelectionPatch, validate_body
from config import DB_BACKEND
from repositories.courses import CourseRepository


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


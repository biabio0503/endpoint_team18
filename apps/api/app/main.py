"""P1 API: anonymous session ownership and persistent basic plan input."""
import os
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json
import re
import secrets
import signal
import sqlite3
import threading
import uuid
from config import APP_ORIGIN, SECURE_COOKIE, API_HOST, API_PORT, DB_BACKEND, validate_deployment
from repositories.p1 import Repository, connect, migrate, StorageUnavailable
from repositories.p2 import CourseRepository
from api.routes.documents import route as document_route
from worker.documents import start_worker
from services.course_recommendations import recommend
from services.gemini import GeminiError

COOKIE = 'roadmap_session'
FIELDS = ('career_goal', 'target_role', 'university_id', 'department_id', 'catalog_id', 'year_level', 'earned_credits', 'gpa', 'gpa_scale')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class Problem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def validate(repo, values):
    goal = values['career_goal']
    if not isinstance(goal, str) or not goal.strip():
        raise Problem(422, "validation_error", "목표·관심 분야를 입력해 주세요.")
    if len(goal) > 10000:
        raise Problem(422, 'validation_error', '목표는 10,000자 이하여야 합니다.')
    values['career_goal'] = goal.strip()
    role = values['target_role']
    if role is not None:
        if not isinstance(role, str) or len(role.strip()) > 100:
            raise Problem(422, 'validation_error', '희망 직무는 100자 이하여야 합니다.')
        values['target_role'] = role.strip() or None
    for name in ('university_id', 'department_id', 'catalog_id'):
        if values[name] is not None and (not isinstance(values[name], str) or len(values[name]) > 100):
            raise Problem(422, 'validation_error', '기준 자료 식별자가 올바르지 않습니다.')
    year = values['year_level']
    if year is not None and (type(year) is not int or not 1 <= year <= 4):
        raise Problem(422, 'validation_error', '학년은 1~4 사이여야 합니다.')
    for name, maximum, places in (('earned_credits', Decimal('9999.9'), 1), ('gpa', Decimal('9.99'), 2), ('gpa_scale', Decimal('9.99'), 2)):
        value = values[name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise Problem(422, 'validation_error', '학점과 GPA는 숫자로 입력해 주세요.')
        try:
            n = Decimal(str(value))
            if not n.is_finite() or n < 0 or n > maximum or n != n.quantize(Decimal(1).scaleb(-places)):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise Problem(422, 'validation_error', '학점 또는 GPA의 범위와 소수 자릿수를 확인해 주세요.')
        values[name] = float(n)
    if values['gpa'] is not None and (values['gpa_scale'] is None or values['gpa_scale'] <= 0 or values['gpa'] > values['gpa_scale']):
        raise Problem(422, 'validation_error', 'GPA는 0 이상 만점 이하이며 만점 기준이 필요합니다.')
    if values['gpa_scale'] is not None and values['gpa_scale'] <= 0:
        raise Problem(422, 'validation_error', 'GPA 만점 기준은 0보다 커야 합니다.')
    university, department, catalog = (values[k] for k in ('university_id', 'department_id', 'catalog_id'))
    if university and not repo.university_valid(university):
        raise Problem(422, 'validation_error', '선택할 수 없는 학교입니다.')
    if department and not repo.department_valid(department, university):
        raise Problem(422, 'validation_error', '학과가 선택한 학교에 속하지 않습니다.')
    if catalog and not repo.catalog_valid(catalog, department, values['_existing_catalog']):
        raise Problem(422, 'validation_error', '과목 목록이 선택한 학과에 속하지 않습니다.')


def payload(row):
    status = 'unavailable' if not row['catalog_id'] else 'unconfirmed'
    if row['catalog_id'] and row['reviewed_catalog_id'] == row['catalog_id'] and row['reviewed_selection_revision'] == row['course_selection_revision'] and row['reviewed_at']:
        status = 'partial' if row['reported_missing_courses'] else 'confirmed'
    return {'request_id': row['request_id'], 'input': {key: row[key] for key in FIELDS}, 'input_revision': row['input_revision'], 'selection_revision': row['course_selection_revision'], 'review_status': status, 'updated_at': row['updated_at']}


def json_value(value):
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, datetime): return value.isoformat(timespec='microseconds')
    raise TypeError('Unsupported JSON value')


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, cookie=None):
        content = json.dumps(body, ensure_ascii=False, allow_nan=False, default=json_value).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def owner(self, repo):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie[COOKIE].value if COOKIE in cookie else ''
        except Exception:
            return None
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        digest = sha256(token.encode()).hexdigest()
        return repo.owner(digest, now())

    def body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 32768:
                raise ValueError
            value = json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeDecodeError):
            raise Problem(400, 'invalid_json', '요청 형식을 확인해 주세요.')

    def run_request(self, method):
        path = urlparse(self.path).path
        if path == '/api/health' and method == 'GET':
            return self.respond(200, {'status': 'ok'})
        if path == '/api/health/db' and method == 'GET':
            with closing(connect()) as db:
                db.execute('SELECT 1').fetchone()
            return self.respond(200, {'status': 'ok'})
        # SameSite is defense in depth; require the configured browser origin for writes.
        if method in ('POST', 'PATCH', 'DELETE') and self.headers.get('Origin', '').rstrip('/') != APP_ORIGIN:
            raise Problem(403, 'invalid_origin', '요청 출처를 확인할 수 없습니다.')
        with closing(connect()) as db:
            repo = Repository(db)
            if method == 'GET' and path == '/api/reference':
                return self.respond(200, repo.reference())
            courses_repo = CourseRepository(db)
            if method == 'GET' and path == '/api/universities':
                return self.respond(200, {'universities': courses_repo.universities()})
            reference_match = re.fullmatch(r'/api/universities/([^/]+)/departments', path)
            if method == 'GET' and reference_match:
                university = courses_repo.university(reference_match[1])
                if not university: raise Problem(404, 'not_found', '학교를 찾을 수 없습니다.')
                return self.respond(200, {'departments': courses_repo.departments(reference_match[1])})
            reference_match = re.fullmatch(r'/api/departments/([^/]+)/catalogs', path)
            if method == 'GET' and reference_match:
                department = courses_repo.department(reference_match[1])
                if not department: raise Problem(404, 'not_found', '학과를 찾을 수 없습니다.')
                catalogs = courses_repo.catalogs(reference_match[1])
                support = 'unsupported' if not department['is_supported'] else 'supported' if catalogs else 'no_catalog'
                return self.respond(200, {'catalogs': catalogs, 'support_status': support})
            owner = self.owner(repo)
            if DB_BACKEND == 'postgres' and re.fullmatch(r'/api/roadmap-inputs/[0-9a-f-]{36}/documents(?:/.*)?', path):
                raise Problem(503, 'feature_unavailable', 'PostgreSQL 문서 기능은 아직 연결되지 않았습니다.')
            if DB_BACKEND != 'postgres' and document_route(self, db, repo, owner, path, method, Problem): return
            if path == '/api/roadmap-inputs' and method == 'POST':
                repo.begin()
                cookie = None
                if owner is None:
                    token = secrets.token_urlsafe(32)
                    owner_id = str(uuid.uuid4())
                    created = now()
                    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec='microseconds')
                    repo.add_owner(owner_id, sha256(token.encode()).hexdigest(), expires, created)
                    cookie = f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000' + ('; Secure' if SECURE_COOKIE else '')
                else:
                    owner_id = owner['owner_id']
                request_id, created = str(uuid.uuid4()), now()
                repo.create_plan(request_id, owner_id, created)
                row = repo.plan(request_id, owner_id)
                repo.commit()
                return self.respond(201, payload(row), cookie)
            if path == '/api/roadmap-inputs/resume' and method == 'GET':
                row = repo.resume(owner['owner_id']) if owner else None
                return self.respond(200, {'found': bool(row), 'request': dict(row) if row else None})
            recommendation_match = re.fullmatch(r'/api/roadmap-inputs/([0-9a-f-]{36})/course-recommendations', path)
            if recommendation_match and method == 'POST':
                if not owner: raise Problem(401, 'unauthorized', '세션이 만료되었거나 유효하지 않습니다.')
                if self.body() != {}: raise Problem(422, 'validation_error', '추천 요청 형식을 확인해 주세요.')
                rid = recommendation_match[1]
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
                    return self.respond(200, {'courses': [], 'status': 'empty_catalog', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal']})
                result = recommend(profile, courses, status)
                # The model call may take time; never return a result for changed input.
                db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
                current = repo.plan(rid, owner['owner_id'])
                if not current or current['input_revision'] != revision or current['catalog_id'] != cid:
                    raise Problem(409, 'revision_conflict', '분석 중 입력이 변경되었습니다. 다시 시도해 주세요.')
                latest = {str(c['course_id']): c for c in courses_repo.courses(rid, cid)}
                result = [dict(latest[str(c['course_id'])], is_completed=False, completion_state=c['completion_state']) for c in result if str(c['course_id']) in latest and not latest[str(c['course_id'])]['is_completed']]
                db.commit()
                return self.respond(200, {'courses': result, 'status': 'ok', 'catalog_id': cid, 'input_revision': revision, 'review_status': status, 'career_goal': profile['career_goal']})
            course_match = re.fullmatch(r'/api/roadmap-inputs/([0-9a-f-]{36})/(courses|course-selections|course-selection-review)', path)
            if course_match:
                rid, action = course_match.groups()
                if not owner: raise Problem(401, 'unauthorized', '세션이 만료되었거나 유효하지 않습니다.')
                if (action, method) not in (('courses', 'GET'), ('course-selections', 'PATCH'), ('course-selection-review', 'POST')):
                    raise Problem(404, 'not_found', '요청한 경로를 찾을 수 없습니다.')
                body = self.body() if method != 'GET' else None
                # Read the entire listing from one snapshot; serialize all writes to the parent row.
                if method == 'GET': db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if DB_BACKEND == 'postgres' else 'BEGIN')
                else: repo.begin()
                row = repo.plan(rid, owner['owner_id'], lock=method != 'GET')
                if not row: raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
                if method == 'GET':
                    query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
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
                    return self.respond(200,result)
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
                    if pending:
                        at=now()
                        for course_id, source_id, target in pending: courses_repo.save_state(rid,course_id,source_id,target,at)
                        courses_repo.changed(rid,at)
                    row=repo.plan(rid,owner['owner_id']); repo.commit()
                    return self.respond(200, {'selection_revision':row['course_selection_revision'],'input_revision':row['input_revision'],'review_status':payload(row)['review_status'],'saved_changes':changes})
                if set(body) != {'catalog_id','expected_selection_revision','expected_input_revision','reported_missing_courses'} or type(body.get('expected_input_revision')) is not int or body['expected_input_revision'] < 0 or type(body.get('reported_missing_courses')) is not bool:
                    raise Problem(422, 'validation_error', '확인 요청을 확인해 주세요.')
                if body['expected_input_revision'] != row['input_revision']: raise Problem(409, 'revision_conflict', '입력이 변경되었습니다. 최신 내용을 불러와 주세요.')
                status = payload(row)['review_status']; missing=body['reported_missing_courses']
                if status not in ('confirmed','partial') or bool(row['reported_missing_courses']) != missing:
                    courses_repo.review(rid,cid,rev,missing,now())
                row=repo.plan(rid,owner['owner_id']); repo.commit()
                return self.respond(200, {'review_status':payload(row)['review_status'],'reviewed_catalog_id':row['reviewed_catalog_id'],'reviewed_selection_revision':row['reviewed_selection_revision'],'reviewed_at':row['reviewed_at'],'input_revision':row['input_revision'],'selection_revision':row['course_selection_revision']})
            match = re.fullmatch(r'/api/roadmap-inputs/([0-9a-f-]{36})', path)
            if match and method in ('GET', 'PATCH'):
                if not owner:
                    raise Problem(401, 'unauthorized', '세션이 만료되었거나 유효하지 않습니다.')
                if method == 'PATCH':
                    body = self.body()
                    if set(body) != {'expected_input_revision', 'changes'} or type(body['expected_input_revision']) is not int or body['expected_input_revision'] < 0 or not isinstance(body['changes'], dict) or not set(body['changes']).issubset(FIELDS):
                        raise Problem(422, 'validation_error', '수정 요청 형식을 확인해 주세요.')
                    repo.begin()
                row = repo.plan(match[1], owner['owner_id'], lock=method == 'PATCH')
                if not row:
                    raise Problem(404, 'not_found', '계획을 찾을 수 없습니다.')
                if method == 'GET':
                    return self.respond(200, payload(row))
                if row['input_revision'] != body['expected_input_revision']:
                    raise Problem(409, 'revision_conflict', '다른 화면에서 입력이 변경되었습니다. 최신 내용을 불러와 확인해 주세요.')
                values = {field: float(row[field]) if isinstance(row[field], Decimal) else row[field] for field in FIELDS}
                values.update(body['changes'])
                values['_existing_catalog'] = row['catalog_id']
                validate(repo, values)
                changed = any(values[k] != (float(row[k]) if isinstance(row[k], Decimal) else row[k]) for k in FIELDS)
                scope_changed = any(values[k] != row[k] for k in ('university_id', 'department_id', 'catalog_id'))
                if changed:
                    repo.update_plan(match[1], FIELDS, values, scope_changed, now())
                result = payload(repo.plan(match[1], owner['owner_id']))
                repo.commit()
                return self.respond(200, result)
            raise Problem(404, 'not_found', '요청한 경로를 찾을 수 없습니다.')

    def handle_request(self, method):
        try:
            self.run_request(method)
        except Problem as error:
            self.respond(error.status, {'error': error.code, 'message': error.message})
        except GeminiError as error:
            self.respond(error.status, {'error': error.code, 'message': error.message})
        except StorageUnavailable as error:
            self.respond(503, {'error': 'storage_unavailable', 'message': str(error)})
        except (sqlite3.Error, OSError):
            self.respond(503, {'error': 'storage_unavailable', 'message': '저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'})

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PATCH(self): self.handle_request('PATCH')
    def do_DELETE(self): self.handle_request('DELETE')


if __name__ == '__main__':
    validate_deployment()
    try:
        migrate()
        if DB_BACKEND == 'postgres':
            with closing(connect()) as db: db.execute('SELECT 1')
    except StorageUnavailable as error:
        raise SystemExit(str(error)) from None
    # This application is a local development MVP. Seed only an empty reference
    # database; deployments can disable fictional data explicitly.
    if DB_BACKEND == 'sqlite' and os.environ.get('ROADMAP_AUTO_SEED_DEV', '1') == '1':
        from scripts.seed_dev import seed
        seed(only_if_empty=True)
    stop_worker = start_worker() if DB_BACKEND == 'sqlite' else None
    server = ThreadingHTTPServer((API_HOST, API_PORT), Handler)
    def stop_server(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    print(f'API listening on {API_HOST}:{API_PORT}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if stop_worker: stop_worker.set()
        server.server_close()

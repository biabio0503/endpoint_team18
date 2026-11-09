import json
import re
import os
import secrets
import uuid
from urllib.request import Request as URLRequest, urlopen
from urllib.error import HTTPError, URLError
from contextlib import closing
from hashlib import sha256
from datetime import datetime
from decimal import Decimal

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.convertors import Convertor, register_url_convertor
from api.domain import COOKIE, Problem, now
from config import APP_ORIGIN, SECURE_COOKIE, DB_BACKEND
from repositories.plans import Repository, connect


class RoadmapIdConvertor(Convertor):
    regex = '[0-9a-f-]{36}'

    def convert(self, value):
        return value

    def to_string(self, value):
        return str(value)


register_url_convertor('roadmap_id', RoadmapIdConvertor())


def get_db():
    with closing(connect()) as db:
        yield db


def get_context(request: Request, db=Depends(get_db)):
    repo = Repository(db)
    if DB_BACKEND == 'postgres':
        authorization = request.headers.get('authorization', '')
        if not authorization:
            return db, repo, None
        if not re.fullmatch(r'Bearer [A-Za-z0-9._-]+', authorization):
            raise Problem(401, 'unauthorized', '인증 정보가 유효하지 않습니다.')
        url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        key = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
        if not url.startswith('https://') or not key:
            raise Problem(503, 'auth_unavailable', '인증 서비스 설정을 확인해 주세요.')
        try:
            req = URLRequest(url + '/auth/v1/user', headers={'Authorization': authorization, 'apikey': key})
            with urlopen(req, timeout=10) as response:
                user = json.load(response)
                user_id = str(uuid.UUID(user['id']))
        except HTTPError as error:
            if error.code in (400, 401, 403):
                raise Problem(401, 'unauthorized', '세션이 만료되었거나 유효하지 않습니다.') from None
            raise Problem(503, 'auth_unavailable', '인증 서비스를 사용할 수 없습니다.') from None
        except (URLError, TimeoutError, ValueError, KeyError, TypeError):
            raise Problem(503, 'auth_unavailable', '인증 서비스를 사용할 수 없습니다.') from None
        # A fresh opaque legacy owner key avoids claiming an existing cookie owner.
        owner_id = str(uuid.uuid4())
        repo.db.execute("INSERT INTO session_owners(owner_id, token_digest, expires_at, created_at, auth_user_id) VALUES(?, ?, ?, ?, ?) ON CONFLICT (auth_user_id) DO NOTHING", (owner_id, sha256(secrets.token_bytes(32)).hexdigest(), '9999-12-31T00:00:00+00:00', now(), user_id))
        owner = repo.db.execute('SELECT owner_id FROM session_owners WHERE auth_user_id=?', (user_id,)).fetchone()
        return db, repo, {**dict(owner), 'is_anonymous': user.get('is_anonymous') is not False}
    token = request.cookies.get(COOKIE, '')
    owner = repo.owner(sha256(token.encode()).hexdigest(), now()) if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
    return db, repo, owner


def require_owner(owner):
    if not owner:
        raise Problem(401, 'unauthorized', '세션이 만료되었거나 유효하지 않습니다.')
    return owner


def owned_context(ctx=Depends(get_context)):
    require_owner(ctx[2])
    return ctx


def require_origin(request: Request):
    if request.headers.get('origin', '').rstrip('/') != APP_ORIGIN:
        raise Problem(403, 'invalid_origin', '요청 출처를 확인할 수 없습니다.')


async def parse_body(request: Request):
    try:
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > 32768:
                raise ValueError
        if not raw:
            raise ValueError
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError):
        raise Problem(400, 'invalid_json', '요청 형식을 확인해 주세요.') from None


def respond(status, body, cookie=None):
    result = JSONResponse(jsonable_encoder(body, custom_encoder={Decimal: float, datetime: lambda value: value.isoformat(timespec='microseconds')}), status_code=status, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    if cookie:
        result.set_cookie(COOKIE, cookie, max_age=2592000, httponly=True, secure=SECURE_COOKIE, samesite='Strict', path='/')
    return result

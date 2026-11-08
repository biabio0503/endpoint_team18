from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
import uuid
from fastapi import APIRouter, Depends
from api.dependencies import get_context, owned_context, parse_body, require_origin, require_owner, respond
from api.domain import now, payload
from api.schemas import PlanPatch, openapi_body
from services.plans import plan_action

router = APIRouter(prefix='/api')

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

@router.get('/roadmap-inputs/{rid:roadmap_id}')
def get_plan(rid: str, ctx=Depends(owned_context)):
    return plan_action(rid, 'GET', None, ctx)

@router.patch('/roadmap-inputs/{rid:roadmap_id}', dependencies=[Depends(require_origin)], openapi_extra=openapi_body(PlanPatch))
def patch_plan(rid: str, ctx=Depends(owned_context), body=Depends(parse_body)):
    require_owner(ctx[2])
    return plan_action(rid, 'PATCH', body, ctx)


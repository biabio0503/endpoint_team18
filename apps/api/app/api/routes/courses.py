from fastapi import APIRouter, Depends, Request
from api.dependencies import owned_context, parse_body, require_origin, require_owner
from api.schemas import SelectionPatch, ReviewRequest, openapi_body
from services.courses import course_action

router = APIRouter(prefix='/api')

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


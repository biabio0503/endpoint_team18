from fastapi import APIRouter, Depends
from api.dependencies import get_context, respond
from api.domain import Problem
from repositories.courses import CourseRepository

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


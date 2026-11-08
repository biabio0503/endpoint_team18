from contextlib import closing
from fastapi import APIRouter
from api.dependencies import respond
from repositories.plans import connect

router = APIRouter()


@router.get('/api/health', tags=['health'])
def health():
    return respond(200, {'status': 'ok'})


@router.get('/api/health/db', tags=['health'])
def database_health():
    with closing(connect()) as db:
        db.execute('SELECT 1').fetchone()
    return respond(200, {'status': 'ok'})



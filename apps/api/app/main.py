"""FastAPI entry point for the existing roadmap API."""
import os
import asyncio
import sqlite3
import sys
from contextlib import asynccontextmanager, closing
from pathlib import Path

# Existing repositories and worker modules use imports relative to the app directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from api.dependencies import respond
from api.domain import Problem
from api.routes import courses, health, jobs, plans, recommendations, reference
from api.routes.documents import router as documents_router
from config import APP_ORIGIN, DB_BACKEND, validate_deployment
from repositories.plans import connect, migrate, StorageUnavailable
from services.gemini import GeminiError
from worker.documents import start_worker


@asynccontextmanager
async def lifespan(application):
    validate_deployment()
    worker = None
    try:
        migrate()
        if DB_BACKEND == 'postgres':
            with closing(connect()) as db:
                db.execute('SELECT 1').fetchone()
        elif os.environ.get('ROADMAP_AUTO_SEED_DEV', '1') == '1':
            from scripts.seed_dev import seed
            seed(only_if_empty=True)
        if DB_BACKEND == 'sqlite':
            worker = start_worker()
        yield
    finally:
        if worker:
            stop, thread = worker
            stop.set()
            await asyncio.to_thread(thread.join, 10)


app = FastAPI(title='Career Roadmap API', version='1.0.0', lifespan=lifespan, redirect_slashes=False)
app.include_router(reference.router)
app.include_router(plans.router)
app.include_router(jobs.router)
app.include_router(recommendations.router)
app.include_router(courses.router)
app.include_router(documents_router)


@app.middleware('http')
async def origin_guard(request, call_next):
    if request.url.path.startswith('/api/') and request.method in ('POST', 'PATCH', 'DELETE') and request.headers.get('origin', '').rstrip('/') != APP_ORIGIN:
        return respond(403, {'error': 'invalid_origin', 'message': '요청 출처를 확인할 수 없습니다.'})
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
def http_error(request, error):
    if error.status_code in (404, 405) and request.url.path.startswith('/api/'):
        return respond(404, {'error': 'not_found', 'message': '요청한 경로를 찾을 수 없습니다.'})
    return respond(error.status_code, {'detail': error.detail})


app.include_router(health.router)


@app.exception_handler(Problem)
@app.exception_handler(GeminiError)
def problem_handler(request, error):
    return respond(error.status, {'error': error.code, 'message': error.message})


@app.exception_handler(StorageUnavailable)
def storage_handler(request, error):
    return respond(503, {'error': 'storage_unavailable', 'message': str(error)})


@app.exception_handler(sqlite3.Error)
@app.exception_handler(OSError)
def database_handler(request, error):
    return respond(503, {'error': 'storage_unavailable', 'message': '저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'})

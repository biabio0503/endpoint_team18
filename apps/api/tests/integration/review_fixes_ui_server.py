"""Disposable browser regression server: real API/SQLite/parser, fixed AI/providers.

Run with the project's Python, then Next dev on :15102 with API origin :18083
and the job-skills-test Supabase public test settings. No credentials needed.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile


def local_only(address):
    if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
        raise AssertionError('Browser regression forbids external network')


original_connect = socket.socket.connect


def connect(sock, address):
    local_only(address)
    return original_connect(sock, address)


socket.socket.connect = connect
temporary = tempfile.TemporaryDirectory(prefix='team18-review-fixes-ui-')
os.environ.update(PYTHON_DOTENV_DISABLED='1', ROADMAP_DB_BACKEND='sqlite',
    ROADMAP_DB_PATH=str(Path(temporary.name) / 'test.db'),
    ROADMAP_FILE_STORAGE_PATH=str(Path(temporary.name) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
    ROADMAP_APP_ORIGIN='http://localhost:15102', ROADMAP_INSECURE_LOCAL_COOKIE='1',
    ROADMAP_OCR_PROVIDER='none', GEMINI_API_KEY='', SUPABASE_URL='',
    SUPABASE_SECRET_KEY='', CONTESTKOREA_API_KEY='', RENDER='false',
    ROADMAP_AI_COOLDOWN_SECONDS='0', ROADMAP_AI_GUEST_HOURLY_UNITS='100000',
    ROADMAP_AI_GUEST_DAILY_UNITS='100000', ROADMAP_AI_GLOBAL_DAILY_UNITS='100000')
sys.path.insert(0, os.environ.get('REVIEW_SOURCE_ROOT', str(Path(__file__).resolve().parents[2])))
from app.main import app
from scripts.seed_dev import seed
from services import gemini_projects, job_skill_analysis, himalayas
from services.gemini import GeminiError
from services.project_experience_schemas import DocumentExperience
from services.job_skill_schemas import RoleInterpretation, BatchExtraction
from api.routes import roadmaps, activities
import roadmap_scenario
from worker import documents as document_worker

real_extract = document_worker.extract


def extraction(extension, data, **kwargs):
    if data == b'LOCAL_EXTRACTION_FAILURE':
        raise ValueError('fixed parser failure after successful upload')
    return real_extract(extension, data, **kwargs)


document_worker.extract = extraction

seed()
roadmap_scenario.DB_COURSE = '40000000-0000-4000-8000-000000000003'
state = {'project_failure': False}
counters = {'project_fixture': 0, 'job_fixture': 0, 'roadmap_fixture': 0, 'provider_fixture': 0}


def project(schema, prompt, doc):
    counters['project_fixture'] += 1
    if state['project_failure']:
        raise GeminiError('gemini_timeout', '고정 응답: 재분석 시간 초과')
    text = doc['extracted_text']
    quote = '제가 SQL을 사용' if text == '제가 SQL을 사용하지 않았습니다.' else text
    return DocumentExperience(document_id=doc['document_id'], extraction_revision=doc['extraction_revision'],
        experiences=[dict(skill_name='SQL', category='database_query_language', activity=text,
                          contribution_scope='personal', evidence_text=quote)])


gemini_projects._generate = project
job_skill_analysis.generate_job_keywords = lambda *args: RoleInterpretation(
    status='success', canonical_role='Data Analyst', search_keywords=[{'keyword': 'Data Analyst', 'relation': 'direct'}],
    clarification_message=None)


def job_extract(jobs):
    counters['job_fixture'] += 1
    return BatchExtraction(jobs=[dict(job_id=j['id'], skills=[dict(name='SQL', category='database_query_language',
        requirement_type='required', evidence_text='SQL is required.')]) for j in jobs])


job_skill_analysis.extract_job_skills = job_extract
himalayas._request_page = lambda keyword, page: {'jobs': [dict(
    guid='https://himalayas.app/companies/review/jobs/data-analyst', title='Junior Data Analyst',
    companyName='Fixed Review', categories=['Data Analyst'],
    description='<h2>Responsibilities</h2><p>Analyze data and build reports.</p><h2>Requirements</h2><p>SQL is required.</p>')]
    if page == 1 else []}


def roadmap(data):
    counters['roadmap_fixture'] += 1
    return roadmap_scenario.fake_roadmap(data)


roadmaps.generate_roadmap = roadmap


def fixed_catalog(db, *, include_event_context=False):
    # Recommendations now read cached DB catalogs, not the removed live catalog object.
    counters['provider_fixture'] += 1
    return [dict(id='review-post', kind='competition', title='SQL 공공데이터 분석 경진대회',
                 category='데이터 분석', host='로컬 고정 기관', target='대학생', period='상시 접수',
                 url='https://www.contestkorea.com/sub/view.php?str_no=review-post')], dict(
                     source='contestkorea', kind='competition', status='success')


activities.load_contestkorea_catalog = fixed_catalog
activities.load_catalog = lambda db, **kwargs: ([], dict(
    source='dacon_daker', kind='competition', status='success'))


@app.get('/api/review-counters')
def count():
    return counters


@app.post('/api/review-fixture')
def fixture(body: dict):
    state['project_failure'] = body.get('project_failure', False)
    return state


if __name__ == '__main__':
    import uvicorn
    try:
        uvicorn.run(app, host='127.0.0.1', port=18083)
    finally:
        temporary.cleanup()

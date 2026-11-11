"""Disposable browser QA API. Real SQLite routes, synthetic auth, no provider I/O.

Run with .venv/bin/python tests/integration/course_groups_ui_server.py.
Next dev: ROADMAP_API_ORIGIN=http://127.0.0.1:18082 and port 15101.
"""
from pathlib import Path
import os
import tempfile
from unittest.mock import patch


with tempfile.TemporaryDirectory(prefix='team18-course-ui-') as tmp:
    os.environ.update(ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'ui.db'),
        ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
        ROADMAP_APP_ORIGIN='http://localhost:15101', ROADMAP_INSECURE_LOCAL_COOKIE='1',
        ROADMAP_AI_COOLDOWN_SECONDS='0', ROADMAP_AI_GUEST_HOURLY_UNITS='100000',
        ROADMAP_AI_GUEST_DAILY_UNITS='100000', ROADMAP_AI_GLOBAL_DAILY_UNITS='100000',
        GEMINI_API_KEY='', ROADMAP_OCR_PROVIDER='none', RENDER='false')
    from course_equivalence_scenario import CourseEquivalenceAPI, ENGLISH, KOREAN, DATA_EN
    from roadmap_scenario import fake_roadmap
    from app.main import app
    from fastapi.responses import JSONResponse
    import uvicorn

    case = CourseEquivalenceAPI('test_legacy_duplicate_roadmap_and_both_step_ids_read_without_ai')
    # The shared API fixture bootstraps using the unit-test origin.
    with patch('app.main.APP_ORIGIN', 'http://localhost:3000'), patch('api.dependencies.APP_ORIGIN', 'http://localhost:3000'):
        case.setUp()
    case.client.headers['Origin'] = 'http://localhost:15101'
    try:
        with patch('course_groups.GROUPS_BY_CATALOG', {}):
            case.jobs()
            def legacy_provider(data):
                with patch('roadmap_scenario.DB_COURSE', ENGLISH):
                    raw = fake_roadmap(data).model_dump()
                raw['recommended_courses'].append({**raw['recommended_courses'][0],
                    'course_id': KOREAN, 'course_evidence': '데이터베이스'})
                raw['roadmap'][1]['related_course_ids'] = [KOREAN]
                raw['roadmap'][2]['related_course_ids'] = [ENGLISH, KOREAN]
                return raw
            with patch('api.routes.roadmaps.generate_roadmap', side_effect=legacy_provider):
                response = case.make()
            assert response.status_code == 201, response.text
        case.legacy_select(ENGLISH, KOREAN, DATA_EN)
        with patch('api.routes.roadmaps.generate_roadmap', side_effect=AssertionError('Unexpected paid request')) as ai:
            @app.get('/api/course-groups-qa')
            def fixture():
                cookie = '; '.join(f'{key}={value}' for key, value in case.client.cookies.items())
                return JSONResponse({'request_id': case.rid, 'states': case.saved_state(),
                                     'ai_calls': ai.call_count}, headers={'Set-Cookie': cookie + '; Path=/; HttpOnly; SameSite=Lax'})
            uvicorn.run(app, host='127.0.0.1', port=18082)
    finally:
        case.doCleanups()

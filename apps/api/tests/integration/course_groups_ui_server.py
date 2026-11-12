"""Disposable browser QA API. Real SQLite routes, synthetic auth, no provider I/O.

Run with .venv/bin/python tests/integration/course_groups_ui_server.py.
Next dev: ROADMAP_API_ORIGIN=http://127.0.0.1:18082 and port 15101.
"""
from contextlib import closing
import json
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
    from repositories.plans import connect
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
            with patch('api.routes.roadmaps.generate_roadmap', side_effect=fake_roadmap):
                response = case.make()
            assert response.status_code == 201, response.text
            # Recreate a pre-ranking stored result, as in the API equivalence regression.
            with closing(connect()) as db:
                run_id = response.json()['run_id']
                saved = json.loads(db.execute('SELECT result_json FROM roadmap_runs WHERE run_id=?', (run_id,)).fetchone()['result_json'])
                english = {'course_id': ENGLISH, 'course_name': 'Database', 'related_skills': ['SQL'], 'evidence_refs': []}
                saved['recommended_courses'] = [english, {**english, 'course_id': KOREAN, 'course_name': '데이터베이스'}]
                for step in saved['roadmap']:
                    step['related_course_ids'] = [ENGLISH]
                saved['roadmap'][1]['related_course_ids'] = [KOREAN]
                saved['roadmap'][2]['related_course_ids'] = [ENGLISH, KOREAN]
                db.execute('UPDATE roadmap_runs SET result_json=? WHERE run_id=?', (json.dumps(saved, ensure_ascii=False), run_id))
                db.commit()
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

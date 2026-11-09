"""Disposable local browser QA server. Never reads deployment DB/Storage or calls AI."""
from pathlib import Path
import os
import sys
import tempfile
from contextlib import closing

with tempfile.TemporaryDirectory(prefix='team18-guest-ui-') as tmp:
    os.environ.update(ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp)/'ui.db'),
        ROADMAP_FILE_STORAGE_PATH=str(Path(tmp)/'files'), ROADMAP_AUTO_SEED_DEV='0',
        ROADMAP_APP_ORIGIN='http://localhost:15101', ROADMAP_INSECURE_LOCAL_COOKIE='1',
        GEMINI_API_KEY='', SUPABASE_URL='', SUPABASE_SECRET_KEY='', RENDER='false')
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from app.main import app
    from repositories.plans import connect
    from scripts.seed_dev import seed, U, C1
    seed()
    with closing(connect()) as db:
        for n in range(30):
            cid, name = f'guest-ui-{n:02}', f'격리 테스트 과목 {n:02}'
            db.execute('INSERT INTO courses(course_id,university_id,canonical_name) VALUES(?,?,?)',(cid,U,name))
            db.execute('INSERT INTO catalog_courses(catalog_id,course_id,course_name,course_code) VALUES(?,?,?,?)',(C1,cid,name,f'AUDIT{n:02}'))
        db.commit()
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18081)

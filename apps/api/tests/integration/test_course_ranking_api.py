"""HTTP regression using isolated SQLite and a mocked roadmap provider."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def test_course_ranking_api():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'db.sqlite'),
                   ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
                   ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000', ROADMAP_AI_COOLDOWN_SECONDS='0', RENDER='false')
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('course_ranking_scenario.py'))], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr

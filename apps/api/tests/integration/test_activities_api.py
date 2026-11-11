"""Run with an isolated SQLite DB; never touches the developer's PostgreSQL .env."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def test_activities_api_isolated():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, ROADMAP_DB_BACKEND='sqlite', ROADMAP_DB_PATH=str(Path(tmp) / 'activities.db'),
                   ROADMAP_FILE_STORAGE_PATH=str(Path(tmp) / 'files'), ROADMAP_AUTO_SEED_DEV='0',
                   ROADMAP_INSECURE_LOCAL_COOKIE='1', ROADMAP_APP_ORIGIN='http://localhost:3000', RENDER='false')
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('activities_scenario.py'))],
                                env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

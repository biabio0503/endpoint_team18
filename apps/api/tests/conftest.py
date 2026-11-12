"""Legacy behavior scenarios intentionally issue many rapid mocked AI requests.

The guard's dedicated tests set small explicit limits and exercise real concurrent
reservations; other tests suppress only time/volume limits, never ownership/leases.
"""
import atexit
import os
from pathlib import Path
import sys
import tempfile

# Set these before pytest imports any test module or application configuration.
# PostgreSQL scenarios opt in through their own test URLs and subprocess setup.
_test_storage = tempfile.TemporaryDirectory(prefix='team18-pytest-')
atexit.register(_test_storage.cleanup)
os.environ.update(PYTHON_DOTENV_DISABLED='1', ROADMAP_DB_BACKEND='sqlite',
                  ROADMAP_DATABASE_URL='', ROADMAP_DB_PATH=str(Path(_test_storage.name) / 'test.sqlite3'),
                  ROADMAP_FILE_STORAGE_PATH=str(Path(_test_storage.name) / 'files'),
                  ROADMAP_AUTO_SEED_DEV='0', ROADMAP_INSECURE_LOCAL_COOKIE='1',
                  ROADMAP_APP_ORIGIN='http://localhost:3000', RENDER='false')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

import pytest

@pytest.fixture(autouse=True)
def isolated_mock_budget(monkeypatch):
    # A developer's local .env or ADC must never enable billable OCR in tests.
    monkeypatch.setenv('ROADMAP_OCR_PROVIDER', 'none')
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', '/nonexistent/team18-test-credentials.json')
    from google.cloud import vision
    def no_real_client(*args, **kwargs):
        raise AssertionError('Real Vision API clients are forbidden in tests')
    monkeypatch.setattr(vision, 'ImageAnnotatorClient', no_real_client)
    for key, value in {'COOLDOWN_SECONDS': '0', 'GUEST_HOURLY_UNITS': '100000',
                       'GUEST_DAILY_UNITS': '100000', 'USER_HOURLY_UNITS': '100000',
                       'USER_DAILY_UNITS': '100000', 'GLOBAL_DAILY_UNITS': '100000'}.items():
        monkeypatch.setenv('ROADMAP_AI_' + key, value)

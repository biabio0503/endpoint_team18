import os
from pathlib import Path
import subprocess
import sys

import pytest

INTEGRATION = Path(__file__).resolve().parents[1] / 'integration'
sys.path.insert(0, str(INTEGRATION))
from postgres_test_safety import validate_reset_target

LOCAL = 'postgresql://test@127.0.0.1:55439/team18_document_test'
OPT_IN = {'ROADMAP_ALLOW_TEST_DB_RESET': '1'}


@pytest.mark.parametrize('url', [
    'postgresql://test@db.example.com:5432/team18_document_test',
    'postgresql://test@127.0.0.1:55439/postgres',
    LOCAL + '?host=production.example.com', LOCAL + '?hostaddr=1.2.3.4',
    LOCAL + '?service=production', LOCAL + '?dbname=postgres',
])
def test_nonlocal_and_overridden_targets_are_rejected(url):
    with pytest.raises(SystemExit):
        validate_reset_target(url, OPT_IN)


def test_opt_in_and_environment_are_checked():
    assert validate_reset_target(LOCAL, OPT_IN) == LOCAL
    for env in ({}, dict(OPT_IN, RENDER='true'), dict(OPT_IN, PGHOSTADDR='1.2.3.4')):
        with pytest.raises(SystemExit):
            validate_reset_target(LOCAL, env)


def test_optimized_python_still_refuses_reset():
    env = dict(os.environ, ROADMAP_TEST_POSTGRES_URL='postgresql://production.example.com/postgres',
               ROADMAP_ALLOW_TEST_DB_RESET='1')
    result = subprocess.run([sys.executable, '-O', str(INTEGRATION / 'postgres_documents_scenario.py')],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Refusing test DB reset' in result.stderr

"""Optional destructive tests for an explicitly named local test database only."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('ROADMAP_TEST_POSTGRES_URL'), reason='isolated PostgreSQL not configured')
def test_postgres_document_api():
    script = Path(__file__).with_name('postgres_documents_scenario.py')
    result = subprocess.run([sys.executable, str(script)], cwd=script.parents[2],
                            env=os.environ.copy(), text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr

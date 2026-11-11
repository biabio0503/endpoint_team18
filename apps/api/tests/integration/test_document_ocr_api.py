import os
from pathlib import Path
import subprocess
import sys


def test_ocr_upload_retry_and_project_analysis(tmp_path):
    env=dict(os.environ,ROADMAP_DB_BACKEND='sqlite',ROADMAP_DB_PATH=str(tmp_path/'ocr.db'),
        ROADMAP_FILE_STORAGE_PATH=str(tmp_path/'files'),ROADMAP_AUTO_SEED_DEV='0',ROADMAP_OCR_PROVIDER='none',
        ROADMAP_INSECURE_LOCAL_COOKIE='1',ROADMAP_APP_ORIGIN='http://localhost:3000',
        GOOGLE_APPLICATION_CREDENTIALS=str(tmp_path/'absent.json'))
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('document_ocr_scenario.py'))],
        env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr

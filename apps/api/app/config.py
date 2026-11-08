"""Runtime configuration for local development and deployment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Explicit environment variables take precedence over the optional local file.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
except ImportError:
    pass
DB_BACKEND = os.environ.get('ROADMAP_DB_BACKEND', 'sqlite').lower()
DATABASE_URL = os.environ.get('ROADMAP_DATABASE_URL', '')
DB_PATH = Path(os.environ.get('ROADMAP_DB_PATH', ROOT / 'var' / 'roadmap.sqlite3'))
APP_ORIGIN = os.environ.get('ROADMAP_APP_ORIGIN', 'http://localhost:3000').rstrip('/')
SECURE_COOKIE = os.environ.get('ROADMAP_INSECURE_LOCAL_COOKIE') != '1'
# Private local document storage; replace its adapter for other storage providers.
FILE_STORAGE_PATH = Path(os.environ.get('ROADMAP_FILE_STORAGE_PATH', ROOT / 'var' / 'files'))

ON_RENDER = os.environ.get('RENDER', '').lower() == 'true'
API_HOST = '0.0.0.0' if ON_RENDER else os.environ.get('ROADMAP_API_HOST', '127.0.0.1')
try:
    API_PORT = int(os.environ.get('PORT', os.environ.get('ROADMAP_API_PORT', '8000')))
    if not 1 <= API_PORT <= 65535:
        raise ValueError
except ValueError:
    raise SystemExit('PORT 또는 ROADMAP_API_PORT는 1~65535 사이의 정수여야 합니다.') from None

def validate_deployment():
    if not ON_RENDER:
        return
    from urllib.parse import urlsplit
    if DB_BACKEND != 'postgres' or not DATABASE_URL:
        raise SystemExit('Render에서는 PostgreSQL과 ROADMAP_DATABASE_URL 설정이 필요합니다.')
    origin = urlsplit(APP_ORIGIN)
    if origin.scheme != 'https' or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username or origin.password:
        raise SystemExit('Render에서는 ROADMAP_APP_ORIGIN에 프론트엔드 HTTPS 출처를 설정해야 합니다.')
    if not SECURE_COOKIE:
        raise SystemExit('Render에서는 보안 쿠키를 비활성화할 수 없습니다.')

MAX_DOCUMENT_BYTES = int(os.environ.get('ROADMAP_MAX_DOCUMENT_BYTES', str(10 * 1024 * 1024)))
MAX_DOCUMENTS = int(os.environ.get('ROADMAP_MAX_DOCUMENTS', '10'))

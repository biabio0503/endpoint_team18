"""Fail closed before the optional destructive local PostgreSQL test."""
from urllib.parse import urlsplit


def validate_reset_target(url, environment):
    try:
        parsed = urlsplit(url)
        allowed = (
            environment.get('ROADMAP_ALLOW_TEST_DB_RESET') == '1'
            and environment.get('RENDER', '').lower() != 'true'
            and not any(environment.get(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'))
            and parsed.scheme in ('postgresql', 'postgres')
            and parsed.hostname in ('127.0.0.1', 'localhost')
            and parsed.port is not None
            and parsed.path == '/team18_document_test'
            and not parsed.query and not parsed.fragment
        )
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        raise SystemExit('Refusing test DB reset: explicit opt-in and a local disposable database are required.')
    return url

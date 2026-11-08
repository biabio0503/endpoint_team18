"""Small psycopg adapter for the P1/P2 SQL; never runs SQLite migrations."""

import logging
import os
import ssl

logger = logging.getLogger(__name__)

class StorageUnavailable(Exception):
    """A safe error which must not expose connection details."""


def _connection_error_code(error):
    """Classify libpq errors without ever returning their potentially secret text."""
    message = str(error).lower()
    if 'password authentication failed' in message or 'authentication failed' in message:
        return 'authentication_failed'
    if 'certificate' in message and ('does not match' in message or 'hostname' in message):
        return 'tls_hostname_mismatch'
    if 'certificate verify failed' in message or 'certificate verification failed' in message:
        return 'tls_verification_failed'
    if 'root certificate' in message or 'sslrootcert' in message:
        return 'tls_ca_error'
    if 'could not translate host name' in message or 'name or service not known' in message or 'nodename nor servname' in message:
        return 'dns_error'
    if 'timeout' in message or 'timed out' in message:
        return 'connection_timeout'
    if 'network is unreachable' in message or 'no route to host' in message:
        return 'network_unreachable'
    if 'invalid connection option' in message or 'invalid dsn' in message or 'invalid uri' in message:
        return 'invalid_dsn'
    return 'connection_failed'


def _validate_ca_file(path):
    # libpq's special "system" value selects the system trust store.
    if not path or path == 'system':
        return
    try:
        with open(path, 'rb') as certificate:
            certificate.read(1)
        ssl.create_default_context(cafile=path)
    except (OSError, ValueError, ssl.SSLError):
        logger.error('PostgreSQL connection failed: tls_ca_error')
        raise StorageUnavailable('PostgreSQL CA 인증서 파일을 읽거나 검증할 수 없습니다. (tls_ca_error)') from None


def connect_postgres(url):
    if not url:
        raise StorageUnavailable('PostgreSQL을 사용하려면 ROADMAP_DATABASE_URL을 설정해 주세요.')
    try:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        from psycopg.rows import dict_row
    except ImportError:
        raise StorageUnavailable('PostgreSQL 드라이버를 설치해 주세요.') from None
    try:
        # An explicit DSN sslrootcert overrides PGSSLROOTCERT in libpq.
        options = conninfo_to_dict(url)
        _validate_ca_file(options.get('sslrootcert', os.environ.get('PGSSLROOTCERT')))
        connection = psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=10, sslmode='verify-full')
        return PostgresConnection(connection, psycopg.Error)
    except (psycopg.Error, ValueError, UnicodeError) as error:
        code = _connection_error_code(error)
        logger.error('PostgreSQL connection failed: %s', code)
        raise StorageUnavailable(f'PostgreSQL 연결에 실패했습니다. 설정과 네트워크를 확인해 주세요. ({code})') from None


class PostgresConnection:
    backend = 'postgres'

    def __init__(self, connection, error_type):
        self.connection = connection
        self.error_type = error_type

    def execute(self, sql, params=()):
        # All P1/P2 statements are static and use ? only as parameter markers.
        try:
            return self.connection.execute(sql.replace('?', '%s'), params)
        except self.error_type:
            raise StorageUnavailable('PostgreSQL 저장소 작업에 실패했습니다.') from None

    def commit(self):
        try:
            self.connection.execute('COMMIT')
        except self.error_type:
            raise StorageUnavailable('PostgreSQL 저장을 완료하지 못했습니다.') from None

    def close(self):
        self.connection.close()

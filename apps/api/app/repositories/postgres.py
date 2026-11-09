"""Small psycopg adapter for the P1/P2 SQL; never runs SQLite migrations."""

import logging
import os

logger = logging.getLogger(__name__)

class StorageUnavailable(Exception):
    """A safe error which must not expose connection details."""


class StorageConflict(StorageUnavailable):
    """Retry a short transaction with a fresh snapshot, never the external AI call."""


def _connection_error_code(error):
    """Classify libpq errors without ever returning their potentially secret text."""
    message = str(error).lower()
    sqlstate = getattr(error, 'sqlstate', None) or ''
    if sqlstate.startswith('28') or 'password authentication failed' in message or 'authentication failed' in message:
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
        options = conninfo_to_dict(url)
        host = options.get('hostaddr') or options.get('host') or os.environ.get('PGHOSTADDR') or os.environ.get('PGHOST', '')
        if not host or any(not part or part.startswith(('/', '@')) for part in host.split(',')):
            raise StorageUnavailable('PostgreSQL 연결에는 TCP 호스트가 필요합니다. (tls_required)')
        options.pop('sslrootcert', None)
        options.pop('sslmode', None)
        options.pop('gssencmode', None)
        options.pop('connect_timeout', None)
        # libpq may load ~/.postgresql/root.crt even with sslmode=require.
        # A child of the /dev/null device cannot exist, so this explicit
        # per-connection sentinel also overrides PGSSLROOTCERT and that default.
        connection = psycopg.connect(**options, autocommit=True, row_factory=dict_row,
                                     connect_timeout=10, sslmode='require',
                                     sslrootcert='/dev/null/roadmap-no-ca', gssencmode='disable')
        if not connection.pgconn.ssl_in_use:
            connection.close()
            logger.error('PostgreSQL connection failed: tls_required')
            raise StorageUnavailable('PostgreSQL 연결에 TLS가 필요합니다. (tls_required)')
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
        except self.error_type as error:
            if getattr(error, 'sqlstate', None) in ('40001', '40P01'):
                raise StorageConflict('동시에 입력이 변경되었습니다.') from None
            raise StorageUnavailable('PostgreSQL 저장소 작업에 실패했습니다.') from None

    def commit(self):
        try:
            self.connection.execute('COMMIT')
        except self.error_type:
            raise StorageUnavailable('PostgreSQL 저장을 완료하지 못했습니다.') from None

    def close(self):
        # Explicit BEGIN is used with autocommit. Always discard unfinished
        # work before releasing this request's dedicated connection.
        from psycopg.pq import TransactionStatus
        try:
            if self.connection.info.transaction_status in (TransactionStatus.INTRANS, TransactionStatus.INERROR):
                self.connection.execute('ROLLBACK')
        except self.error_type:
            logger.warning('PostgreSQL rollback before close failed')
        finally:
            self.connection.close()

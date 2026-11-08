"""Small psycopg adapter for the P1/P2 SQL; never runs SQLite migrations."""

class StorageUnavailable(Exception):
    """A safe error which must not expose connection details."""


def connect_postgres(url):
    if not url:
        raise StorageUnavailable('PostgreSQL을 사용하려면 ROADMAP_DATABASE_URL을 설정해 주세요.')
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        raise StorageUnavailable('PostgreSQL 드라이버를 설치해 주세요.') from None
    try:
        connection = psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=10, sslmode='verify-full')
        return PostgresConnection(connection, psycopg.Error)
    except (psycopg.Error, ValueError, UnicodeError):
        raise StorageUnavailable('PostgreSQL 연결에 실패했습니다. 연결 설정과 네트워크를 확인해 주세요.') from None


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

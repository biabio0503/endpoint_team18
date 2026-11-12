"""Run against an explicitly supplied disposable local PostgreSQL database."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest


def test_postgres_keyword_repository_and_migration():
    url = os.environ.get('COURSE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('disposable PostgreSQL URL not configured')
    parsed = urlsplit(url)
    assert parsed.hostname in ('localhost', '127.0.0.1') and parsed.path == '/team18_course_test'
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from repositories.postgres import PostgresConnection
    from repositories.courses import CourseRepository
    from services.course_recommendations import rank_courses
    schema = 'course_test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            connection.execute('''CREATE TABLE courses(course_id text PRIMARY KEY, university_id text);
                CREATE TABLE catalog_courses(catalog_id text, course_id text, course_name text, course_code text,
                  credits numeric, category text, recommended_year integer, recommended_term text,
                  theory_hours integer, practice_hours integer, description_text text, PRIMARY KEY(catalog_id,course_id));
                CREATE TABLE input_course_states(request_id text, course_id text, is_completed boolean);
                CREATE TABLE verified_course_equivalences(course_id text, equivalent_course_id text);''')
            path = next((Path(__file__).resolve().parents[4] / 'supabase/migrations').glob('*_course_keyword_evidence.sql'))
            migration = path.read_text().replace('public.', schema + '.')
            connection.execute(migration)
            connection.execute(migration)  # Existing production table/data are preserved.
            connection.execute("INSERT INTO courses VALUES ('web','school'),('data','school')")
            connection.execute("""INSERT INTO catalog_courses(catalog_id,course_id,course_name,description_text)
                VALUES ('catalog','web','웹프로그래밍','Java script 원리를 배운다.'),
                       ('catalog','data','데이터분석','Python 사전지식이 필요하다.')""")
            connection.execute("""INSERT INTO catalog_course_keywords VALUES
                ('catalog','web','JavaScript','learning','Java script 원리를 배운다.',54,54),
                ('catalog','data','Python','prerequisite','Python 사전지식이 필요하다.',52,52)""")
            repo = CourseRepository(PostgresConnection(connection, psycopg.Error))
            courses = repo.recommendation_courses('request', 'catalog')
            ranked = rank_courses({'career_goal':'JavaScript 경험 없음'}, courses, 'confirmed')
            assert [c['course_id'] for c in ranked] == ['web', 'data']
            assert ranked[0]['course_evidence'] == 'Java script 원리를 배운다.'
            assert ranked[1]['recommendation_type'] != 'direct'
            assert connection.execute('SELECT count(*) n FROM catalog_course_keywords').fetchone()['n'] == 2
        finally:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

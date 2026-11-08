"""Backend boundary tests; live PostgreSQL requires an explicitly configured DSN."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))
from repositories.postgres import PostgresConnection, StorageUnavailable, connect_postgres
from repositories import p1


class PostgresBoundaryTest(unittest.TestCase):
    def test_no_dsn_fails_without_secret(self):
        env = dict(os.environ, ROADMAP_DB_BACKEND='postgres', ROADMAP_DATABASE_URL='')
        result = subprocess.run([sys.executable, str(APP / 'main.py')], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ROADMAP_DATABASE_URL', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_failed_connection_hides_driver_message(self):
        import psycopg
        with patch('psycopg.connect', side_effect=psycopg.OperationalError('sensitive-value')):
            with self.assertRaises(StorageUnavailable) as caught:
                connect_postgres('sensitive-value')
        self.assertNotIn('sensitive-value', str(caught.exception))

    def test_invalid_unicode_hostname_is_sanitized(self):
        error = UnicodeEncodeError('idna', 'sensitive-value', 0, 1, 'invalid label')
        with patch('psycopg.connect', side_effect=error):
            with self.assertRaises(StorageUnavailable) as caught:
                connect_postgres('sensitive-value')
        self.assertNotIn('sensitive-value', str(caught.exception))

    def test_parameter_binding_and_row_lock(self):
        connection = Mock()
        adapter = PostgresConnection(connection, RuntimeError)
        with patch.object(p1, 'DB_BACKEND', 'postgres'):
            repo = p1.Repository(adapter)
            repo.begin()
            repo.plan('request', 'owner', lock=True)
        self.assertEqual(connection.execute.call_args_list[0].args[0], 'BEGIN')
        sql, params = connection.execute.call_args_list[1].args
        self.assertEqual(sql, 'SELECT * FROM roadmap_inputs WHERE request_id=%s AND owner_id=%s FOR UPDATE')
        self.assertEqual(params, ('request', 'owner'))

    def test_postgres_values_serialize_and_validate(self):
        import main
        encoded = json.dumps({'n': Decimal('3.25'), 't': datetime(2026, 1, 1, tzinfo=timezone.utc)}, default=main.json_value)
        self.assertEqual(json.loads(encoded), {'n': 3.25, 't': '2026-01-01T00:00:00.000000+00:00'})
        values = dict.fromkeys(main.FIELDS)
        values.update(career_goal='test', earned_credits=Decimal('3.5'), _existing_catalog=None)
        main.validate(Mock(), values)
        self.assertEqual(values['earned_credits'], 3.5)

    def test_postgres_migration_and_seed_are_not_run(self):
        with patch.object(p1, 'DB_BACKEND', 'postgres'), patch.object(p1, 'connect') as connect:
            p1.migrate()
            connect.assert_not_called()
        from scripts import seed_dev
        with patch.object(seed_dev, 'DB_BACKEND', 'postgres'), patch.object(seed_dev, 'migrate') as migrate:
            with self.assertRaises(RuntimeError): seed_dev.seed()
            migrate.assert_not_called()


if __name__ == '__main__': unittest.main()

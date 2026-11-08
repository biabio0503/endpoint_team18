import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
import repositories.plans as storage
from scripts.seed_dev import seed


class DevelopmentSeedTest(unittest.TestCase):
    def test_empty_database_is_seeded_and_existing_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'DB_PATH', Path(directory) / 'test.sqlite3'):
            self.assertTrue(seed(only_if_empty=True))
            with storage.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM universities').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM departments').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM course_catalogs').fetchone()[0], 2)
                db.execute("UPDATE universities SET university_name='기존 데이터'")
            self.assertFalse(seed(only_if_empty=True))
            with storage.connect() as db:
                self.assertEqual(db.execute('SELECT university_name FROM universities').fetchone()[0], '기존 데이터')

    def test_existing_school_does_not_receive_fictional_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'DB_PATH', Path(directory) / 'test.sqlite3'):
            storage.migrate()
            with storage.connect() as db:
                db.execute("INSERT INTO universities VALUES ('existing', '기존 학교', 1)")
            self.assertFalse(seed(only_if_empty=True))
            with storage.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM universities').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM departments').fetchone()[0], 0)

"""Database connection and persistence for sessions, plans and reference data."""
from contextlib import closing
import os
import sqlite3
from config import DB_PATH, ROOT, DB_BACKEND, DATABASE_URL
from repositories.postgres import connect_postgres, StorageUnavailable


def connect():
    if DB_BACKEND == 'postgres':
        return connect_postgres(DATABASE_URL)
    if DB_BACKEND != 'sqlite':
        raise StorageUnavailable('ROADMAP_DB_BACKEND는 sqlite 또는 postgres여야 합니다.')
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def migrate():
    if DB_BACKEND == 'postgres':
        return
    if DB_BACKEND != 'sqlite':
        raise StorageUnavailable('ROADMAP_DB_BACKEND는 sqlite 또는 postgres여야 합니다.')
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(DB_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    with closing(connect()) as db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)')
        for file in sorted((ROOT / 'migrations').glob('*.sql')):
            if not db.execute('SELECT 1 FROM schema_migrations WHERE name=?', (file.name,)).fetchone():
                escaped = file.name.replace("'", "''")
                db.executescript('BEGIN IMMEDIATE;\n' + file.read_text() + f"\nINSERT INTO schema_migrations VALUES ('{escaped}');\nCOMMIT;")


class Repository:
    def __init__(self, db): self.db = db
    def begin(self): self.db.execute('BEGIN' if DB_BACKEND == 'postgres' else 'BEGIN IMMEDIATE')
    def commit(self): self.db.commit()
    def owner(self, digest, at):
        return self.db.execute('SELECT owner_id FROM session_owners WHERE token_digest=? AND expires_at>?', (digest, at)).fetchone()
    def add_owner(self, owner_id, digest, expires, created):
        self.db.execute('INSERT INTO session_owners(owner_id,token_digest,expires_at,created_at) VALUES(?,?,?,?)', (owner_id, digest, expires, created))
    def create_plan(self, request_id, owner_id, created):
        self.db.execute('INSERT INTO roadmap_inputs(request_id,owner_id,created_at,updated_at) VALUES(?,?,?,?)', (request_id, owner_id, created, created))
    def plan(self, request_id, owner_id, lock=False):
        sql = 'SELECT * FROM roadmap_inputs WHERE request_id=? AND owner_id=?'
        if lock and DB_BACKEND == 'postgres': sql += ' FOR UPDATE'
        return self.db.execute(sql, (request_id, owner_id)).fetchone()
    def resume(self, owner_id):
        return self.db.execute('SELECT request_id,updated_at FROM roadmap_inputs WHERE owner_id=? ORDER BY updated_at DESC, created_at DESC, request_id DESC LIMIT 1', (owner_id,)).fetchone()
    def reference(self):
        return {'universities':[dict(r) for r in self.db.execute('SELECT university_id, university_name FROM universities WHERE is_supported=TRUE ORDER BY university_name, university_id')], 'departments':[dict(r) for r in self.db.execute('SELECT department_id, university_id, department_name FROM departments WHERE is_supported=TRUE ORDER BY department_name, department_id')], 'catalogs':[dict(r) for r in self.db.execute('SELECT catalog_id, department_id, version_label, scope_description, source_name, retrieved_at FROM course_catalogs WHERE is_selectable=TRUE ORDER BY version_label, catalog_id')]}
    def university_valid(self, university):
        return bool(self.db.execute('SELECT 1 FROM universities WHERE university_id=? AND is_supported=TRUE', (university,)).fetchone())
    def department_valid(self, department, university):
        return bool(self.db.execute('SELECT 1 FROM departments WHERE department_id=? AND university_id=? AND is_supported=TRUE', (department, university)).fetchone())
    def catalog_valid(self, catalog, department, existing):
        return bool(self.db.execute('SELECT 1 FROM course_catalogs WHERE catalog_id=? AND department_id=? AND (is_selectable=TRUE OR catalog_id=?)', (catalog, department, existing)).fetchone())
    def update_plan(self, request_id, fields, values, scope_changed, updated):
        assignments = ', '.join(k + '=?' for k in fields)
        self.db.execute(f'UPDATE roadmap_inputs SET {assignments}, input_revision=input_revision+1, course_selection_revision=course_selection_revision+?, reviewed_catalog_id=CASE WHEN ? THEN NULL ELSE reviewed_catalog_id END, reviewed_selection_revision=CASE WHEN ? THEN NULL ELSE reviewed_selection_revision END, reviewed_at=CASE WHEN ? THEN NULL ELSE reviewed_at END, updated_at=? WHERE request_id=?', [values[k] for k in fields] + [int(scope_changed)] + [bool(scope_changed)] * 3 + [updated, request_id])

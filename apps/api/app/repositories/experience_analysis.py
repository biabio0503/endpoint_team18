"""Owner authorization is through the locked parent plan; JSON works on both adapters."""
import json
import uuid

from api.domain import now


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


class AnalysisRepository:
    def __init__(self, db):
        self.db = db

    def encode(self, value):
        if getattr(self.db, 'backend', 'sqlite') == 'postgres':
            from psycopg.types.json import Jsonb
            return Jsonb(value)
        return json.dumps(value, ensure_ascii=False)

    def job(self, rid, basis):
        row = self.db.execute('SELECT * FROM job_skill_snapshots WHERE request_id=? AND basis_key=?', (rid, basis)).fetchone()
        return dict(row) if row else None

    def save_job(self, rid, basis, revision, result):
        # An explicit refresh replaces the snapshot ID and invalidates skill answers.
        self.db.execute('DELETE FROM job_skill_snapshots WHERE request_id=? AND basis_key=?', (rid, basis))
        self.db.execute('INSERT INTO job_skill_snapshots VALUES(?,?,?,?,?,?)',
                        (str(uuid.uuid4()), rid, basis, revision, self.encode(result), now()))
        return self.job(rid, basis)

    def analyses(self, rid, version):
        rows = self.db.execute('SELECT * FROM project_experience_analyses WHERE request_id=? AND analysis_version=?', (rid, version))
        return {(r['document_id'], r['extraction_revision']): dict(r) for r in rows}

    def save_document(self, rid, document, version, revision, result):
        # Stable winner if concurrent requests both analyzed the same version.
        existing = self.analyses(rid, version).get((document['document_id'], document['extraction_revision']))
        if existing:
            if decode(existing['result_json'])['status'] in ('success', 'partial'):
                return
            self.db.execute('DELETE FROM project_experience_analyses WHERE analysis_id=?', (existing['analysis_id'],))
        self.db.execute('''INSERT INTO project_experience_analyses VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(document_id,extraction_revision,analysis_version) DO NOTHING''',
            (result['analysis_id'], rid, document['document_id'], document['extraction_revision'], version,
             revision, self.encode(result), now()))

    def answers(self, rid):
        return {r['experience_id']: {**dict(r), 'correction': decode(r['correction_json'])}
                for r in self.db.execute('''SELECT a.* FROM project_experience_answers a
                    JOIN project_experience_analyses p ON p.analysis_id=a.analysis_id WHERE p.request_id=?''', (rid,))}

    def save_answer(self, item, answer, revision):
        correction = self.encode(answer.correction.model_dump()) if answer.correction else None
        self.db.execute('''INSERT INTO project_experience_answers VALUES(?,?,?,?,?,?)
            ON CONFLICT(experience_id) DO UPDATE SET status=excluded.status,correction_json=excluded.correction_json,
            input_revision=excluded.input_revision,updated_at=excluded.updated_at''',
            (item['experience_id'], item['analysis_id'], answer.status, correction, revision, now()))

    def skill_answers(self, snapshot_id, document_basis):
        return {r['skill_key']: dict(r) for r in self.db.execute(
            'SELECT * FROM skill_experience_answers WHERE snapshot_id=? AND document_basis=?', (snapshot_id, document_basis))}

    def save_skill_answer(self, snapshot_id, basis, key, status, revision):
        self.db.execute('''INSERT INTO skill_experience_answers VALUES(?,?,?,?,?,?)
            ON CONFLICT(snapshot_id,document_basis,skill_key) DO UPDATE SET status=excluded.status,
            input_revision=excluded.input_revision,updated_at=excluded.updated_at''',
            (snapshot_id, basis, key, status, revision, now()))

"""Caller must authorize/lock the parent plan before all reads and writes."""
import uuid
from datetime import datetime, timedelta, timezone

from api.domain import now
from repositories.experience_analysis import AnalysisRepository, decode
from services.project_experience import digest


class RoadmapRepository(AnalysisRepository):
    def get(self, rid, run_id):
        row = self.db.execute('SELECT * FROM roadmap_runs WHERE request_id=? AND run_id=?', (rid, run_id)).fetchone()
        return dict(row) if row else None

    def history(self, rid):
        return [dict(r) for r in self.db.execute('SELECT * FROM roadmap_runs WHERE request_id=? ORDER BY created_at DESC,run_id DESC', (rid,))]

    def reusable(self, rid, basis_hash):
        row = self.db.execute("""SELECT * FROM roadmap_runs WHERE request_id=? AND basis_hash=?
            AND status IN ('success','partial') ORDER BY created_at DESC,run_id DESC LIMIT 1""", (rid, basis_hash)).fetchone()
        return dict(row) if row else None

    def active(self, rid):
        row = self.db.execute("SELECT * FROM roadmap_runs WHERE request_id=? AND status='generating'", (rid,)).fetchone()
        return dict(row) if row else None

    def expire(self, rid):
        self.db.execute("""UPDATE roadmap_runs SET status='failed',error_code='generation_expired',finished_at=?
            WHERE request_id=? AND status='generating' AND lease_until<?""", (now(), rid, now()))

    def create(self, rid, basis):
        run_id, created = str(uuid.uuid4()), now()
        lease = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
        self.db.execute('''INSERT INTO roadmap_runs(run_id,request_id,input_revision,basis_hash,catalog_id,
            basis_json,status,model_name,rules_version,created_at,lease_until) VALUES(?,?,?,?,?,?,'generating',?,?,?,?)''',
            (run_id, rid, basis['input_revision'], digest(basis), basis['profile']['catalog_id'], self.encode(basis),
             basis['model_name'], basis['rules_version'], created, lease))
        return self.get(rid, run_id)

    def fail(self, rid, run_id, code):
        self.db.execute("""UPDATE roadmap_runs SET status='failed',error_code=?,finished_at=?
            WHERE request_id=? AND run_id=? AND status='generating'""", (code, now(), rid, run_id))

    def finish(self, rid, run_id, result):
        self.db.execute("""UPDATE roadmap_runs SET status=?,result_json=?,finished_at=?
            WHERE request_id=? AND run_id=? AND status='generating'""", (result['status'], self.encode(result), now(), rid, run_id))
        for step in result['roadmap']:
            for task in step['tasks']:
                self.db.execute('INSERT INTO roadmap_task_progress(run_id,task_id,is_completed,updated_at) VALUES(?,?,FALSE,?)',
                                (run_id, task['task_id'], now()))
        return self.get(rid, run_id)

    def progress(self, run_id):
        return {r['task_id']: dict(r) for r in self.db.execute('SELECT * FROM roadmap_task_progress WHERE run_id=?', (run_id,))}

    def update_progress(self, run_id, task_id, completed, version):
        return self.db.execute('''UPDATE roadmap_task_progress SET is_completed=?,progress_version=progress_version+1,updated_at=?
            WHERE run_id=? AND task_id=? AND progress_version=?''', (completed, now(), run_id, task_id, version)).rowcount


def metadata(run, current):
    basis = decode(run['basis_json'])
    restricted = basis['document_basis'] != current['document_basis']
    lease = run['lease_until'] if isinstance(run['lease_until'], datetime) else datetime.fromisoformat(run['lease_until'])
    return {k: run[k] for k in ('run_id', 'request_id', 'input_revision', 'catalog_id', 'basis_hash', 'status', 'model_name',
                                'rules_version', 'created_at', 'finished_at', 'error_code')} | {
        'is_stale': run['basis_hash'] != digest(current), 'current_input_revision': current['input_revision'],
        'details_restricted': restricted,
        'restriction_reason': 'document_basis_changed' if restricted else None,
        'generation_expired': run['status'] == 'generating' and lease < datetime.now(timezone.utc),
    }


def run_payload(store, run, current):
    meta = metadata(run, current)
    if meta['details_restricted'] or run['status'] not in ('success', 'partial'):
        return meta
    result = decode(run['result_json'])
    progress = store.progress(run['run_id'])
    for step in result['roadmap']:
        for task in step['tasks']:
            saved = progress[task['task_id']]
            task.update(is_completed=bool(saved['is_completed']), progress_version=saved['progress_version'], updated_at=saved['updated_at'])
    return {**result, **meta, 'progress': {'completed': sum(bool(p['is_completed']) for p in progress.values()), 'total': len(progress)}}

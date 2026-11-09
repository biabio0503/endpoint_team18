-- SQLite ONLY. PostgreSQL file lives in supabase/migrations/.
CREATE TABLE roadmap_runs (
 run_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES roadmap_inputs(request_id) ON DELETE CASCADE,
 input_revision INTEGER NOT NULL CHECK(input_revision >= 0),
 basis_hash TEXT NOT NULL,
 catalog_id TEXT,
 basis_json TEXT NOT NULL,
 result_json TEXT,
 status TEXT NOT NULL CHECK(status IN ('generating','success','partial','failed')),
 model_name TEXT NOT NULL,
 rules_version TEXT NOT NULL,
 created_at TEXT NOT NULL,
 finished_at TEXT,
 lease_until TEXT NOT NULL,
 error_code TEXT,
 CHECK((status IN ('success','partial') AND result_json IS NOT NULL) OR (status IN ('generating','failed') AND result_json IS NULL))
);
CREATE UNIQUE INDEX roadmap_one_generation ON roadmap_runs(request_id) WHERE status='generating';
CREATE INDEX roadmap_runs_history ON roadmap_runs(request_id,created_at DESC,run_id);
CREATE INDEX roadmap_runs_reuse ON roadmap_runs(request_id,basis_hash,created_at DESC) WHERE status IN ('success','partial');
CREATE TABLE roadmap_task_progress (
 run_id TEXT NOT NULL REFERENCES roadmap_runs(run_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL,
 is_completed INTEGER NOT NULL DEFAULT 0 CHECK(is_completed IN (0,1)),
 progress_version INTEGER NOT NULL DEFAULT 0 CHECK(progress_version >= 0),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(run_id,task_id)
);

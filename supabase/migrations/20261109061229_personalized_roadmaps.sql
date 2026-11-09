-- PostgreSQL ONLY. Additive; no existing tables/data or migration history changed.
-- Backend connection owns authorization through roadmap_inputs.owner_id.
CREATE TABLE public.roadmap_runs (
 run_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES public.roadmap_inputs(request_id) ON DELETE CASCADE,
 input_revision INTEGER NOT NULL CHECK(input_revision >= 0),
 basis_hash TEXT NOT NULL,
 catalog_id TEXT,
 basis_json JSONB NOT NULL,
 result_json JSONB,
 status TEXT NOT NULL CHECK(status IN ('generating','success','partial','failed')),
 model_name TEXT NOT NULL,
 rules_version TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 finished_at TIMESTAMPTZ,
 lease_until TIMESTAMPTZ NOT NULL,
 error_code TEXT,
 CHECK((status IN ('success','partial') AND result_json IS NOT NULL) OR (status IN ('generating','failed') AND result_json IS NULL))
);
CREATE UNIQUE INDEX roadmap_one_generation ON public.roadmap_runs(request_id) WHERE status='generating';
CREATE INDEX roadmap_runs_history ON public.roadmap_runs(request_id,created_at DESC,run_id);
CREATE INDEX roadmap_runs_reuse ON public.roadmap_runs(request_id,basis_hash,created_at DESC) WHERE status IN ('success','partial');
CREATE TABLE public.roadmap_task_progress (
 run_id TEXT NOT NULL REFERENCES public.roadmap_runs(run_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL,
 is_completed BOOLEAN NOT NULL DEFAULT FALSE,
 progress_version INTEGER NOT NULL DEFAULT 0 CHECK(progress_version >= 0),
 updated_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(run_id,task_id)
);
ALTER TABLE public.roadmap_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.roadmap_task_progress ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.roadmap_runs, public.roadmap_task_progress FROM PUBLIC, anon, authenticated;

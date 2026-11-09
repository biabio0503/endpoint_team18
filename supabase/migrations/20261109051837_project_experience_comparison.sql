-- Additive backend-only snapshots; no existing tables or data are reset.
CREATE TABLE public.job_skill_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES public.roadmap_inputs(request_id) ON DELETE CASCADE,
 basis_key TEXT NOT NULL,
 input_revision INTEGER NOT NULL,
 result_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(request_id,basis_key)
);
CREATE TABLE public.project_experience_analyses (
 analysis_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES public.roadmap_inputs(request_id) ON DELETE CASCADE,
 document_id TEXT NOT NULL,
 extraction_revision INTEGER NOT NULL,
 analysis_version TEXT NOT NULL,
 input_revision INTEGER NOT NULL,
 result_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(document_id,extraction_revision,analysis_version),
 FOREIGN KEY(document_id,extraction_revision) REFERENCES public.document_extractions(document_id,extraction_revision) ON DELETE CASCADE
);
CREATE INDEX project_experience_request ON public.project_experience_analyses(request_id);
CREATE TABLE public.project_experience_answers (
 experience_id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES public.project_experience_analyses(analysis_id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('confirmed','corrected','unknown','no_experience')),
 correction_json JSONB,
 input_revision INTEGER NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 CHECK((status='corrected' AND correction_json IS NOT NULL) OR (status<>'corrected' AND correction_json IS NULL))
);
CREATE INDEX project_answer_analysis ON public.project_experience_answers(analysis_id);
CREATE TABLE public.skill_experience_answers (
 snapshot_id TEXT NOT NULL REFERENCES public.job_skill_snapshots(snapshot_id) ON DELETE CASCADE,
 document_basis TEXT NOT NULL,
 skill_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('unknown','no_experience')),
 input_revision INTEGER NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(snapshot_id,document_basis,skill_key)
);
ALTER TABLE public.job_skill_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_experience_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_experience_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skill_experience_answers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.job_skill_snapshots, public.project_experience_analyses, public.project_experience_answers, public.skill_experience_answers FROM PUBLIC, anon, authenticated;

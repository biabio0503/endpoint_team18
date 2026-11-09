CREATE TABLE job_skill_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES roadmap_inputs(request_id) ON DELETE CASCADE,
 basis_key TEXT NOT NULL,
 input_revision INTEGER NOT NULL,
 result_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(request_id,basis_key)
);
CREATE TABLE project_experience_analyses (
 analysis_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL REFERENCES roadmap_inputs(request_id) ON DELETE CASCADE,
 document_id TEXT NOT NULL,
 extraction_revision INTEGER NOT NULL,
 analysis_version TEXT NOT NULL,
 input_revision INTEGER NOT NULL,
 result_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(document_id,extraction_revision,analysis_version),
 FOREIGN KEY(document_id,extraction_revision) REFERENCES document_extractions(document_id,extraction_revision) ON DELETE CASCADE
);
CREATE INDEX project_experience_request ON project_experience_analyses(request_id);
CREATE TABLE project_experience_answers (
 experience_id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES project_experience_analyses(analysis_id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('confirmed','corrected','unknown','no_experience')),
 correction_json TEXT,
 input_revision INTEGER NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK((status='corrected' AND correction_json IS NOT NULL) OR (status<>'corrected' AND correction_json IS NULL))
);
CREATE INDEX project_answer_analysis ON project_experience_answers(analysis_id);
CREATE TABLE skill_experience_answers (
 snapshot_id TEXT NOT NULL REFERENCES job_skill_snapshots(snapshot_id) ON DELETE CASCADE,
 document_basis TEXT NOT NULL,
 skill_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('unknown','no_experience')),
 input_revision INTEGER NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,document_basis,skill_key)
);

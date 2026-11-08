CREATE TABLE project_documents (
 document_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES roadmap_inputs(request_id),
 original_filename TEXT NOT NULL, mime_type TEXT NOT NULL, file_size_bytes INTEGER NOT NULL,
 storage_key TEXT NOT NULL UNIQUE, extraction_status TEXT NOT NULL CHECK(extraction_status IN ('pending','ready','partial','needs_ocr','failed')),
 extraction_revision INTEGER NOT NULL, extraction_error_code TEXT, partial_confirmed_at TEXT,
 created_at TEXT NOT NULL, extraction_attempts INTEGER NOT NULL DEFAULT 0,
 extraction_lease_until TEXT, extraction_lease_token TEXT,
 removed_at TEXT, cleanup_status TEXT NOT NULL DEFAULT 'not_required' CHECK(cleanup_status IN ('not_required','queued','running','succeeded','failed')),
 cleanup_attempts INTEGER NOT NULL DEFAULT 0, cleanup_lease_until TEXT, cleanup_lease_token TEXT, cleanup_error_code TEXT
);
CREATE INDEX project_documents_request ON project_documents(request_id, removed_at, created_at);
CREATE INDEX project_documents_jobs ON project_documents(extraction_status, removed_at, extraction_lease_until);
CREATE TABLE document_extractions (
 document_id TEXT NOT NULL REFERENCES project_documents(document_id), extraction_revision INTEGER NOT NULL,
 extracted_text TEXT, segments TEXT NOT NULL DEFAULT '[]', extraction_status TEXT NOT NULL CHECK(extraction_status IN ('pending','ready','partial','needs_ocr','failed')),
 limitations TEXT NOT NULL DEFAULT '[]', error_code TEXT, created_at TEXT NOT NULL, finished_at TEXT,
 PRIMARY KEY(document_id, extraction_revision)
);

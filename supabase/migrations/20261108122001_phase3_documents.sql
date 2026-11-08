-- Additive only. Do not apply until verified against an isolated copy.
-- Deliberately fail if a table exists rather than silently accepting an
-- incompatible pre-existing schema. Supabase tracks migration versions.
CREATE TABLE public.project_documents (
 document_id text PRIMARY KEY,
 request_id text NOT NULL REFERENCES public.roadmap_inputs(request_id),
 original_filename text NOT NULL,
 mime_type text NOT NULL,
 file_size_bytes bigint NOT NULL CHECK (file_size_bytes > 0 AND file_size_bytes <= 10485760),
 storage_key text NOT NULL UNIQUE,
 extraction_status text NOT NULL CHECK (extraction_status IN ('pending','ready','partial','needs_ocr','failed')),
 extraction_revision integer NOT NULL CHECK (extraction_revision > 0),
 extraction_error_code text,
 partial_confirmed_at timestamptz,
 created_at timestamptz NOT NULL,
 extraction_attempts integer NOT NULL DEFAULT 0 CHECK (extraction_attempts >= 0),
 extraction_lease_until timestamptz,
 extraction_lease_token text,
 removed_at timestamptz,
 cleanup_status text NOT NULL DEFAULT 'not_required' CHECK (cleanup_status IN ('not_required','queued','running','succeeded','failed')),
 cleanup_attempts integer NOT NULL DEFAULT 0 CHECK (cleanup_attempts >= 0),
 cleanup_lease_until timestamptz,
 cleanup_lease_token text,
 cleanup_error_code text
);
CREATE INDEX project_documents_request ON public.project_documents(request_id, removed_at, created_at);
CREATE INDEX project_documents_jobs ON public.project_documents(extraction_status, removed_at, extraction_lease_until);
CREATE INDEX project_documents_cleanup_jobs ON public.project_documents(cleanup_status, cleanup_lease_until) WHERE removed_at IS NOT NULL;

CREATE TABLE public.document_extractions (
 document_id text NOT NULL REFERENCES public.project_documents(document_id),
 extraction_revision integer NOT NULL CHECK (extraction_revision > 0),
 extracted_text text,
 segments jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(segments) = 'array'),
 extraction_status text NOT NULL CHECK (extraction_status IN ('pending','ready','partial','needs_ocr','failed')),
 limitations jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(limitations) = 'array'),
 error_code text,
 created_at timestamptz NOT NULL,
 finished_at timestamptz,
 PRIMARY KEY (document_id, extraction_revision)
);

-- No public policies: anonymous sessions are authorized by FastAPI, not
-- Supabase Auth. The backend connects with its privileged database role.
ALTER TABLE public.project_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_extractions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.project_documents, public.document_extractions FROM PUBLIC, anon, authenticated;

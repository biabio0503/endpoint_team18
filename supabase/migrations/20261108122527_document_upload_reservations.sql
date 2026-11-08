CREATE TABLE public.document_upload_reservations (
 storage_key text PRIMARY KEY,
 request_id text NOT NULL REFERENCES public.roadmap_inputs(request_id),
 created_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 committed_at timestamptz,
 cleanup_lease_token text,
 cleanup_lease_until timestamptz,
 cleanup_attempts integer NOT NULL DEFAULT 0 CHECK (cleanup_attempts >= 0),
 cleanup_error_code text
);
CREATE INDEX document_upload_reservations_request ON public.document_upload_reservations(request_id, expires_at);
CREATE INDEX document_upload_reservations_cleanup ON public.document_upload_reservations(expires_at, cleanup_lease_until);
ALTER TABLE public.document_upload_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.document_upload_reservations FROM PUBLIC, anon, authenticated;

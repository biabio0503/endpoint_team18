-- Additive only. Apply after existing document migrations, with explicit approval.
-- The backend alone accesses this ledger. Keep billing tombstones after deletion.
CREATE TABLE public.document_ocr_units (
 document_id text NOT NULL REFERENCES public.project_documents(document_id),
 unit_key text NOT NULL,
 extraction_revision integer NOT NULL CHECK (extraction_revision > 0),
 usage_month text NOT NULL CHECK (usage_month ~ '^[0-9]{4}-[0-9]{2}$'),
 status text NOT NULL CHECK (status IN ('reserved','completed','failed')),
 error_code text,
 result_json text,
 created_at timestamptz NOT NULL,
 PRIMARY KEY(document_id, unit_key)
);
CREATE INDEX document_ocr_units_month ON public.document_ocr_units(usage_month);
ALTER TABLE public.document_ocr_units ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.document_ocr_units FROM PUBLIC, anon, authenticated;

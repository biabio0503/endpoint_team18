-- Apply in one transaction, with OCR disabled and old workers stopped.
-- UTC timestamps and legacy usage_month remain unchanged. Never delete usage.
ALTER TABLE public.document_ocr_units ADD COLUMN billing_period text;
UPDATE public.document_ocr_units
 SET billing_period = to_char(created_at AT TIME ZONE 'America/Los_Angeles', 'YYYY-MM');
ALTER TABLE public.document_ocr_units ALTER COLUMN billing_period SET NOT NULL;
ALTER TABLE public.document_ocr_units ADD CONSTRAINT document_ocr_units_billing_period_check
 CHECK (billing_period = to_char(created_at AT TIME ZONE 'America/Los_Angeles', 'YYYY-MM'));
CREATE INDEX document_ocr_units_billing_period ON public.document_ocr_units(billing_period);
-- Existing RLS, revoked grants, primary key, foreign key and cached results remain.

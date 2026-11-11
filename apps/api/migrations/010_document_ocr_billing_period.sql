-- Runs in the migration runner's transaction. Rebuild to enforce NOT NULL and
-- preserve every reservation, unique key, UTC timestamp, status and cached result.
-- ocr_billing_period is registered by repositories.plans.connect using ZoneInfo.
CREATE TABLE document_ocr_units_pacific (
 document_id TEXT NOT NULL REFERENCES project_documents(document_id),
 unit_key TEXT NOT NULL,
 extraction_revision INTEGER NOT NULL,
 usage_month TEXT NOT NULL,
 billing_period TEXT NOT NULL CHECK(billing_period = ocr_billing_period(created_at)),
 status TEXT NOT NULL CHECK(status IN ('reserved','completed','failed')),
 error_code TEXT,
 result_json TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY(document_id, unit_key)
);
INSERT INTO document_ocr_units_pacific
 (document_id,unit_key,extraction_revision,usage_month,billing_period,status,error_code,result_json,created_at)
 SELECT document_id,unit_key,extraction_revision,usage_month,ocr_billing_period(created_at),
        status,error_code,result_json,created_at FROM document_ocr_units;
DROP TABLE document_ocr_units;
ALTER TABLE document_ocr_units_pacific RENAME TO document_ocr_units;
CREATE INDEX document_ocr_units_month ON document_ocr_units(usage_month);
CREATE INDEX document_ocr_units_billing_period ON document_ocr_units(billing_period);

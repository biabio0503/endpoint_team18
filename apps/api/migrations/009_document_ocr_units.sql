-- Append-only billing tombstones. Deletion erases result_json, not usage.
CREATE TABLE document_ocr_units (
 document_id TEXT NOT NULL REFERENCES project_documents(document_id),
 unit_key TEXT NOT NULL,
 extraction_revision INTEGER NOT NULL,
 usage_month TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('reserved','completed','failed')),
 error_code TEXT,
 result_json TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY(document_id, unit_key)
);
CREATE INDEX document_ocr_units_month ON document_ocr_units(usage_month);

CREATE TABLE external_sources (
 source_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, base_url TEXT NOT NULL,
 source_kinds TEXT NOT NULL, collection_method TEXT NOT NULL,
 source_environment TEXT NOT NULL CHECK(source_environment IN ('fixture','live')),
 adapter_name TEXT NOT NULL, collection_policy TEXT NOT NULL, freshness_ttl_seconds INTEGER,
 is_enabled INTEGER NOT NULL DEFAULT 0 CHECK(is_enabled IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE external_collection_jobs (
 collection_job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES external_sources(source_id),
 job_key TEXT NOT NULL, scope_snapshot TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','partial','failed')),
 coverage_status TEXT NOT NULL CHECK(coverage_status IN ('complete','partial','unknown')),
 counts TEXT NOT NULL, cursor_checkpoint TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
 lease_until TEXT, lease_token TEXT, retry_at TEXT, error_code TEXT,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, UNIQUE(source_id,job_key)
);
CREATE INDEX external_jobs_queue ON external_collection_jobs(status,retry_at,lease_until);
CREATE TABLE external_items (
 external_item_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES external_sources(source_id),
 source_item_key TEXT NOT NULL, canonical_url TEXT NOT NULL,
 item_kind TEXT NOT NULL CHECK(item_kind IN ('job_posting','competition','extracurricular')),
 latest_version_id TEXT REFERENCES external_item_versions(item_version_id),
 latest_validation_job_id TEXT REFERENCES external_collection_jobs(collection_job_id),
 last_collected_at TEXT, last_confirmed_at TEXT, last_check_attempt_at TEXT,
 check_status TEXT NOT NULL CHECK(check_status IN ('not_checked','confirmed','failed','not_found')),
 check_error_code TEXT, recruitment_status TEXT NOT NULL DEFAULT 'unknown' CHECK(recruitment_status IN ('open','closed','unknown')),
 first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(source_id,source_item_key)
);
CREATE TABLE external_item_versions (
 item_version_id TEXT PRIMARY KEY, external_item_id TEXT NOT NULL REFERENCES external_items(external_item_id),
 collection_job_id TEXT NOT NULL REFERENCES external_collection_jobs(collection_job_id), version_no INTEGER NOT NULL,
 content_hash TEXT NOT NULL, version_fingerprint TEXT NOT NULL, parser_version TEXT NOT NULL,
 source_url TEXT NOT NULL, title TEXT, content_type TEXT NOT NULL, raw_content BLOB NOT NULL,
 source_text TEXT NOT NULL, segments TEXT NOT NULL, source_facts TEXT NOT NULL, recruitment_facts TEXT NOT NULL,
 parse_status TEXT NOT NULL CHECK(parse_status IN ('ready','partial')), limitations TEXT NOT NULL,
 collected_at TEXT NOT NULL, confirmed_at TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(external_item_id,version_no)
);
CREATE INDEX external_versions_item ON external_item_versions(external_item_id,version_no);

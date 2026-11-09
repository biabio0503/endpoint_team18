-- Additive only. AI reservations survive workers/restarts; only recommendation IDs/metadata are cached; no document text or tokens.
CREATE TABLE ai_requests (
 request_id TEXT PRIMARY KEY,
 owner_id TEXT NOT NULL REFERENCES session_owners(owner_id),
 operation TEXT NOT NULL,
 basis_hash TEXT NOT NULL,
 units INTEGER NOT NULL CHECK(units > 0),
 status TEXT NOT NULL CHECK(status IN ('running','finished','failed')),
 created_at TEXT NOT NULL,
 lease_until TEXT NOT NULL,
 result_json TEXT
);
CREATE INDEX ai_requests_owner_time ON ai_requests(owner_id,created_at);
CREATE INDEX ai_requests_time ON ai_requests(created_at);
CREATE INDEX ai_requests_cache ON ai_requests(owner_id,operation,basis_hash,created_at);

-- Only explicitly verified, mutually substitutable pairs. Never infer by title/code.
CREATE TABLE verified_course_equivalences (
 course_id TEXT NOT NULL REFERENCES courses(course_id),
 equivalent_course_id TEXT NOT NULL REFERENCES courses(course_id),
 relation_type TEXT NOT NULL CHECK(relation_type IN ('same','substitute')),
 source_url TEXT NOT NULL CHECK(length(source_url) > 0),
 verification_note TEXT NOT NULL CHECK(length(verification_note) > 0),
 verified_at TEXT NOT NULL,
 PRIMARY KEY(course_id,equivalent_course_id),
 CHECK(course_id < equivalent_course_id)
);

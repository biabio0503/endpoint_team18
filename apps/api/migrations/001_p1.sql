CREATE TABLE session_owners (
  owner_id TEXT PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL, last_seen_at TEXT
);
CREATE TABLE universities (
  university_id TEXT PRIMARY KEY, university_name TEXT NOT NULL,
  is_supported INTEGER NOT NULL CHECK (is_supported IN (0,1))
);
CREATE TABLE departments (
  department_id TEXT PRIMARY KEY, university_id TEXT NOT NULL REFERENCES universities(university_id),
  department_name TEXT NOT NULL, is_supported INTEGER NOT NULL CHECK (is_supported IN (0,1))
);
CREATE TABLE course_catalogs (
  catalog_id TEXT PRIMARY KEY, department_id TEXT NOT NULL REFERENCES departments(department_id),
  curriculum_year INTEGER, version_label TEXT NOT NULL, scope_description TEXT NOT NULL,
  completeness_status TEXT NOT NULL CHECK (completeness_status IN ('complete','partial','unknown')),
  source_name TEXT NOT NULL, source_url TEXT, retrieved_at TEXT NOT NULL, published_at TEXT,
  is_selectable INTEGER NOT NULL CHECK (is_selectable IN (0,1))
);
CREATE TABLE roadmap_inputs (
  request_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES session_owners(owner_id),
  career_goal TEXT, target_role TEXT, university_id TEXT REFERENCES universities(university_id),
  department_id TEXT REFERENCES departments(department_id), catalog_id TEXT REFERENCES course_catalogs(catalog_id),
  year_level INTEGER, earned_credits NUMERIC, gpa NUMERIC, gpa_scale NUMERIC,
  input_revision INTEGER NOT NULL DEFAULT 0, course_selection_revision INTEGER NOT NULL DEFAULT 0,
  reviewed_catalog_id TEXT REFERENCES course_catalogs(catalog_id), reviewed_selection_revision INTEGER,
  reported_missing_courses INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX roadmap_inputs_owner_recent ON roadmap_inputs(owner_id, updated_at DESC, created_at DESC, request_id DESC);

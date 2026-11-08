CREATE TABLE courses (
  course_id TEXT PRIMARY KEY,
  university_id TEXT NOT NULL REFERENCES universities(university_id),
  canonical_name TEXT NOT NULL,
  source_course_code TEXT,
  retired_at TEXT
);
CREATE TABLE catalog_courses (
  catalog_id TEXT NOT NULL REFERENCES course_catalogs(catalog_id),
  course_id TEXT NOT NULL REFERENCES courses(course_id),
  course_name TEXT NOT NULL,
  course_code TEXT,
  credits NUMERIC CHECK (credits IS NULL OR credits >= 0),
  category TEXT,
  recommended_year INTEGER,
  recommended_term TEXT,
  description_text TEXT,
  description_source_url TEXT,
  PRIMARY KEY (catalog_id, course_id)
);
CREATE TABLE input_course_states (
  request_id TEXT NOT NULL REFERENCES roadmap_inputs(request_id),
  course_id TEXT NOT NULL REFERENCES courses(course_id),
  source_catalog_id TEXT NOT NULL,
  is_completed INTEGER NOT NULL CHECK (is_completed IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (request_id, course_id),
  FOREIGN KEY (source_catalog_id, course_id) REFERENCES catalog_courses(catalog_id, course_id)
);
CREATE INDEX course_states_request_completed ON input_course_states(request_id, is_completed);

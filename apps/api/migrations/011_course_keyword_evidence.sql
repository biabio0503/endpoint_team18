ALTER TABLE catalog_courses ADD COLUMN description_page_start INTEGER;
ALTER TABLE catalog_courses ADD COLUMN description_page_end INTEGER;
CREATE TABLE catalog_course_keywords (
  catalog_id TEXT NOT NULL,
  course_id TEXT NOT NULL,
  keyword TEXT NOT NULL,
  keyword_role TEXT NOT NULL CHECK (keyword_role IN ('learning','prerequisite','tool','example','context')),
  evidence_text TEXT NOT NULL,
  evidence_page_start INTEGER,
  evidence_page_end INTEGER,
  FOREIGN KEY (catalog_id, course_id) REFERENCES catalog_courses(catalog_id, course_id)
);
CREATE INDEX catalog_course_keywords_course ON catalog_course_keywords(catalog_id, course_id);

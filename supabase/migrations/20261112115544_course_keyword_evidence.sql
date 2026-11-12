-- Match the existing production evidence schema without rewriting catalog data.
ALTER TABLE public.catalog_courses ADD COLUMN IF NOT EXISTS description_page_start integer;
ALTER TABLE public.catalog_courses ADD COLUMN IF NOT EXISTS description_page_end integer;
CREATE TABLE IF NOT EXISTS public.catalog_course_keywords (
  catalog_id text NOT NULL,
  course_id text NOT NULL,
  keyword text NOT NULL CHECK (btrim(keyword) <> ''),
  keyword_role text NOT NULL CHECK (keyword_role IN ('learning','prerequisite','tool','example','context')),
  evidence_text text NOT NULL CHECK (btrim(evidence_text) <> ''),
  evidence_page_start integer CHECK (evidence_page_start >= 1),
  evidence_page_end integer CHECK (evidence_page_end >= evidence_page_start),
  PRIMARY KEY (catalog_id, course_id, keyword, keyword_role),
  FOREIGN KEY (catalog_id, course_id) REFERENCES public.catalog_courses(catalog_id, course_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS catalog_course_keywords_lookup ON public.catalog_course_keywords(catalog_id, keyword_role, keyword);
ALTER TABLE public.catalog_course_keywords ENABLE ROW LEVEL SECURITY;

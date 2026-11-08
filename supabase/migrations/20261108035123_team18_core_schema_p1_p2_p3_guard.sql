
CREATE TABLE public.session_owners (
 owner_id TEXT PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE,
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ
);
CREATE TABLE public.universities (
 university_id TEXT PRIMARY KEY, university_name TEXT NOT NULL, is_supported BOOLEAN NOT NULL
);
CREATE TABLE public.departments (
 department_id TEXT PRIMARY KEY, university_id TEXT NOT NULL REFERENCES public.universities(university_id),
 department_name TEXT NOT NULL, is_supported BOOLEAN NOT NULL
);
CREATE TABLE public.course_catalogs (
 catalog_id TEXT PRIMARY KEY, department_id TEXT NOT NULL REFERENCES public.departments(department_id),
 curriculum_year INTEGER, version_label TEXT NOT NULL, scope_description TEXT NOT NULL,
 completeness_status TEXT NOT NULL CHECK (completeness_status IN ('complete','partial','unknown')),
 source_name TEXT NOT NULL, source_url TEXT, retrieved_at TIMESTAMPTZ NOT NULL,
 published_at TIMESTAMPTZ, is_selectable BOOLEAN NOT NULL
);
CREATE TABLE public.roadmap_inputs (
 request_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES public.session_owners(owner_id),
 career_goal TEXT, target_role TEXT,
 university_id TEXT REFERENCES public.universities(university_id),
 department_id TEXT REFERENCES public.departments(department_id),
 catalog_id TEXT REFERENCES public.course_catalogs(catalog_id),
 year_level INTEGER, earned_credits NUMERIC, gpa NUMERIC, gpa_scale NUMERIC,
 input_revision INTEGER NOT NULL DEFAULT 0, course_selection_revision INTEGER NOT NULL DEFAULT 0,
 reviewed_catalog_id TEXT REFERENCES public.course_catalogs(catalog_id),
 reviewed_selection_revision INTEGER, reported_missing_courses BOOLEAN NOT NULL DEFAULT FALSE,
 reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX roadmap_inputs_owner_recent ON public.roadmap_inputs
 (owner_id, updated_at DESC, created_at DESC, request_id DESC);
CREATE TABLE public.courses (
 course_id TEXT PRIMARY KEY, university_id TEXT NOT NULL REFERENCES public.universities(university_id),
 canonical_name TEXT NOT NULL, source_course_code TEXT, retired_at TIMESTAMPTZ
);
CREATE TABLE public.catalog_courses (
 catalog_id TEXT NOT NULL REFERENCES public.course_catalogs(catalog_id),
 course_id TEXT NOT NULL REFERENCES public.courses(course_id), course_name TEXT NOT NULL,
 course_code TEXT, credits NUMERIC CHECK (credits IS NULL OR credits >= 0),
 category TEXT, recommended_year INTEGER, recommended_term TEXT,
 description_text TEXT, description_source_url TEXT, PRIMARY KEY (catalog_id, course_id)
);
CREATE TABLE public.input_course_states (
 request_id TEXT NOT NULL REFERENCES public.roadmap_inputs(request_id),
 course_id TEXT NOT NULL REFERENCES public.courses(course_id),
 source_catalog_id TEXT NOT NULL, is_completed BOOLEAN NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (request_id, course_id),
 FOREIGN KEY (source_catalog_id, course_id)
 REFERENCES public.catalog_courses(catalog_id,course_id)
);
CREATE INDEX course_states_request_completed ON public.input_course_states (request_id, is_completed);
CREATE FUNCTION public.check_catalog_course_university()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
 catalog_university TEXT;
 course_university TEXT;
BEGIN
 SELECT d.university_id INTO catalog_university
 FROM public.course_catalogs AS cc
 JOIN public.departments AS d ON d.department_id=cc.department_id
 WHERE cc.catalog_id=NEW.catalog_id;
 SELECT c.university_id INTO course_university
 FROM public.courses AS c WHERE c.course_id=NEW.course_id;
 IF catalog_university IS NULL OR course_university IS NULL OR catalog_university<>course_university THEN
  RAISE EXCEPTION 'catalog_course_university_mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER catalog_course_university_insert_update
BEFORE INSERT OR UPDATE OF catalog_id,course_id
ON public.catalog_courses FOR EACH ROW EXECUTE FUNCTION public.check_catalog_course_university();
ALTER TABLE public.session_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.universities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_catalogs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.roadmap_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.catalog_courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.input_course_states ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.session_owners,public.universities,public.departments,
 public.course_catalogs,public.roadmap_inputs,public.courses,public.catalog_courses,
 public.input_course_states FROM anon,authenticated;
REVOKE ALL ON FUNCTION public.check_catalog_course_university() FROM PUBLIC,anon,authenticated;


ALTER TABLE public.catalog_courses
  ADD COLUMN theory_hours INTEGER CHECK (theory_hours IS NULL OR theory_hours >= 0),
  ADD COLUMN practice_hours INTEGER CHECK (practice_hours IS NULL OR practice_hours >= 0);

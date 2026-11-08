-- Read-only. Run before and after the approved migrations; no user rows returned.
BEGIN READ ONLY;
SELECT 'universities' AS table_name, count(*) AS row_count FROM public.universities
UNION ALL SELECT 'departments', count(*) FROM public.departments
UNION ALL SELECT 'courses', count(*) FROM public.courses
UNION ALL SELECT 'catalog_courses', count(*) FROM public.catalog_courses
UNION ALL SELECT 'roadmap_inputs', count(*) FROM public.roadmap_inputs
UNION ALL SELECT 'session_owners', count(*) FROM public.session_owners;

SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version;
SELECT to_regclass('public.project_documents') AS documents,
       to_regclass('public.document_extractions') AS extractions,
       to_regclass('public.document_upload_reservations') AS reservations;
SELECT conrelid::regclass AS table_name, convalidated, pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conrelid, conname;
SELECT relname, relrowsecurity,
       has_table_privilege('anon',oid,'SELECT') AS anon_select,
       has_table_privilege('authenticated',oid,'SELECT') AS authenticated_select
FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' ORDER BY relname;
SELECT id, public, file_size_limit, allowed_mime_types FROM storage.buckets;
SELECT schemaname, tablename, policyname, roles, cmd
FROM pg_policies WHERE schemaname IN ('public','storage') ORDER BY schemaname,tablename,policyname;
COMMIT;

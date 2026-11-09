-- PostgreSQL READ ONLY. Run before deployment, after separately approved migration.
BEGIN READ ONLY;
SELECT table_name,column_name,data_type
FROM information_schema.columns
WHERE table_schema='public' AND table_name IN ('roadmap_runs','roadmap_task_progress')
ORDER BY table_name,ordinal_position;
SELECT c.relname,c.relrowsecurity,
       has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS anon_access,
       has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS authenticated_access
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname IN ('roadmap_runs','roadmap_task_progress');
SELECT tablename,indexname,indexdef FROM pg_indexes
WHERE schemaname='public' AND tablename IN ('roadmap_runs','roadmap_task_progress');
SELECT conrelid::regclass,conname,pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid IN ('public.roadmap_runs'::regclass,'public.roadmap_task_progress'::regclass);
COMMIT;

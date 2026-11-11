-- Read-only before/after report. No document text, filenames, IDs or secrets.
-- Missing tables/columns are reported, never created. Review every result.
-- Run while all writers are stopped for comparable counts/fingerprints.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path TO public, pg_catalog;
SET LOCAL timezone TO 'UTC';
SET LOCAL lock_timeout TO '3s';
SET LOCAL statement_timeout TO '30s';

SELECT current_setting('transaction_read_only') AS read_only,
       current_setting('server_version') AS postgres_version,
       clock_timestamp() AS observed_at_utc,
       to_char(clock_timestamp() AT TIME ZONE 'America/Los_Angeles', 'YYYY-MM') AS billing_period;

WITH expected(name) AS (VALUES ('project_documents'), ('document_extractions'),
    ('document_upload_reservations'), ('document_ocr_units'))
SELECT e.name, c.oid IS NOT NULL AS present, c.relrowsecurity AS rls_enabled,
       CASE WHEN EXISTS (SELECT FROM pg_roles WHERE rolname='anon')
            THEN has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END AS anon_any,
       CASE WHEN EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated')
            THEN has_table_privilege('authenticated', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END AS authenticated_any,
       EXISTS (SELECT FROM aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
               WHERE a.grantee=0) AS public_any
FROM expected e LEFT JOIN pg_class c
  ON c.oid=to_regclass(format('%I.%I', current_schema(), e.name)) ORDER BY e.name;

WITH expected(name, type, required) AS (VALUES
    ('document_id','text',true), ('unit_key','text',true),
    ('extraction_revision','int4',true), ('usage_month','text',true),
    ('billing_period','text',true), ('status','text',true),
    ('error_code','text',false), ('result_json','text',false), ('created_at','timestamptz',true))
SELECT e.name, e.type AS expected_type, c.udt_name AS actual_type,
       c.is_nullable, c.column_default,
       coalesce(c.udt_name=e.type AND (c.is_nullable='NO')=e.required, false) AS matches
FROM expected e LEFT JOIN information_schema.columns c
  ON c.table_schema=current_schema() AND c.table_name='document_ocr_units' AND c.column_name=e.name
ORDER BY e.name;

SELECT conname, convalidated, pg_get_constraintdef(oid) AS definition
FROM pg_constraint WHERE conrelid=to_regclass('document_ocr_units') ORDER BY conname;
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname=current_schema() AND tablename='document_ocr_units' ORDER BY indexname;
SELECT policyname, roles, cmd FROM pg_policies
WHERE schemaname=current_schema() AND tablename='document_ocr_units' ORDER BY policyname;

-- The same period conversion expected from Python ZoneInfo, with PST and PDT.
SELECT at, expected, to_char(at AT TIME ZONE 'America/Los_Angeles','YYYY-MM')=expected AS matches
FROM (VALUES
    ('2026-01-01 07:59:59+00'::timestamptz,'2025-12'),
    ('2026-01-01 08:00:00+00'::timestamptz,'2026-01'),
    ('2026-07-01 06:59:59+00'::timestamptz,'2026-06'),
    ('2026-07-01 07:00:00+00'::timestamptz,'2026-07')) t(at,expected);

DO $$
DECLARE
    t text;
    r record;
    total bigint;
    fingerprint text;
    invalid bigint;
    has_period boolean;
BEGIN
    IF to_regclass('supabase_migrations.schema_migrations') IS NULL THEN
        RAISE NOTICE 'ocr_preflight migration_history_missing';
    ELSE
        FOR r IN EXECUTE 'SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version' LOOP
            RAISE NOTICE 'ocr_preflight migration %', row_to_json(r);
        END LOOP;
    END IF;

    FOREACH t IN ARRAY ARRAY['project_documents', 'document_extractions',
                            'document_upload_reservations', 'document_ocr_units',
                            'project_experience_analyses', 'project_experience_answers',
                            'skill_experience_answers'] LOOP
        IF to_regclass(format('%I.%I', current_schema(), t)) IS NULL THEN
            RAISE NOTICE 'ocr_preflight table_missing %', t;
            CONTINUE;
        END IF;
        -- Only the new derived field is excluded. Existing UTC fields, status,
        -- revisions and cached text contribute to an aggregate checksum.
        -- MD5 here detects accidental changes; it is not a security signature.
        EXECUTE format('SELECT count(*), md5(coalesce(string_agg(h, '''' ORDER BY h), ''''))
            FROM (SELECT md5((to_jsonb(x) - %L)::text) h FROM %I.%I x) s',
            CASE WHEN t='document_ocr_units' THEN 'billing_period' ELSE '__no_excluded_column__' END,
            current_schema(), t) INTO total, fingerprint;
        RAISE NOTICE 'ocr_preflight snapshot %', jsonb_build_object(
            'table',t,'rows',total,'legacy_fingerprint',fingerprint);
    END LOOP;

    IF to_regclass('document_ocr_units') IS NOT NULL THEN
        SELECT EXISTS (SELECT FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='document_ocr_units'
              AND column_name='billing_period') INTO has_period;
        -- Usable before the new column exists, and comparable after backfill.
        FOR r IN EXECUTE $sql$
            SELECT to_char(created_at AT TIME ZONE 'America/Los_Angeles','YYYY-MM') AS expected_period,
                   count(*) AS units, count(*) FILTER (WHERE status='reserved') AS reserved,
                   count(*) FILTER (WHERE status='completed') AS completed,
                   count(*) FILTER (WHERE status='failed') AS failed,
                   count(*) FILTER (WHERE result_json IS NOT NULL) AS cached,
                   greatest(0,900-count(*)) AS remaining_at_hard_ceiling
            FROM document_ocr_units GROUP BY 1 ORDER BY 1
        $sql$ LOOP
            RAISE NOTICE 'ocr_preflight budget %', row_to_json(r);
        END LOOP;
        IF has_period THEN
            EXECUTE $sql$SELECT count(*) FROM document_ocr_units
                WHERE billing_period IS DISTINCT FROM
                to_char(created_at AT TIME ZONE 'America/Los_Angeles','YYYY-MM')$sql$ INTO invalid;
            RAISE NOTICE 'ocr_preflight invalid_billing_period_rows %', invalid;
        ELSE
            RAISE NOTICE 'ocr_preflight billing_period_missing';
        END IF;
        EXECUTE 'SELECT count(*) FROM document_ocr_units u LEFT JOIN project_documents d USING(document_id)
                 WHERE d.document_id IS NULL' INTO invalid;
        RAISE NOTICE 'ocr_preflight orphan_ocr_units %', invalid;
    END IF;

    IF to_regclass('project_documents') IS NOT NULL THEN
        SELECT count(*) INTO total FROM project_documents
        WHERE extraction_lease_until > clock_timestamp() OR cleanup_lease_until > clock_timestamp();
        RAISE NOTICE 'ocr_preflight active_document_leases %', total;
    END IF;
    IF to_regclass('document_upload_reservations') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM document_upload_reservations
                 WHERE cleanup_lease_until > clock_timestamp()' INTO total;
        RAISE NOTICE 'ocr_preflight active_upload_cleanup_leases %', total;
    END IF;
END $$;
COMMIT;

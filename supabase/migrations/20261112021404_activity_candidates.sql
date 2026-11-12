-- Current candidates are independent from successful daily discovery snapshots.
CREATE TABLE public.activity_candidates (
    source text NOT NULL CHECK (source IN ('contestkorea','dacon','daker')),
    original_id text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    state text NOT NULL CHECK (state IN ('pending','active','expired','closed','cancelled','unknown','ineligible')),
    deadline_at timestamptz,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    last_checked_at timestamptz,
    last_success_at timestamptz NOT NULL,
    next_check_at timestamptz NOT NULL,
    check_status text NOT NULL,
    missing_since timestamptz,
    PRIMARY KEY (source, original_id)
);
CREATE INDEX activity_candidates_due ON public.activity_candidates(source,next_check_at)
    WHERE state IN ('active','pending');
ALTER TABLE public.activity_candidates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.activity_candidates FROM PUBLIC, anon, authenticated;

ALTER TABLE public.dacon_collection_runs DROP CONSTRAINT dacon_collection_runs_status_check;
ALTER TABLE public.dacon_collection_runs ADD CHECK (status IN ('running','success','partial','failed','already_running','already_succeeded'));
ALTER TABLE public.contestkorea_collection_runs DROP CONSTRAINT contestkorea_collection_runs_status_check;
ALTER TABLE public.contestkorea_collection_runs ADD CHECK (status IN ('running','success','partial','failed','already_running','already_succeeded'));
ALTER TABLE public.dacon_collection_runs ADD COLUMN metrics jsonb NOT NULL DEFAULT '{}';
ALTER TABLE public.contestkorea_collection_runs ADD COLUMN metrics jsonb NOT NULL DEFAULT '{}';

-- Latest known version of EACH identity across ALL dates, including identities
-- absent from the latest snapshot. No historical table/row is deleted.
INSERT INTO public.activity_candidates
(source,original_id,payload,state,first_seen_at,last_seen_at,last_success_at,next_check_at,check_status)
SELECT source, original_id, payload, 'pending', first_seen, succeeded_at, succeeded_at, succeeded_at, 'historical'
FROM (
    SELECT DISTINCT ON (i.source,i.original_id) i.source,i.original_id,i.payload,s.succeeded_at,
        min(s.succeeded_at) OVER (PARTITION BY i.source,i.original_id) AS first_seen
    FROM public.dacon_daily_items i JOIN public.dacon_daily_snapshots s USING (collection_date)
    ORDER BY i.source,i.original_id,i.collection_date DESC
) latest;
INSERT INTO public.activity_candidates
(source,original_id,payload,state,first_seen_at,last_seen_at,last_success_at,next_check_at,check_status)
SELECT 'contestkorea',original_id,payload,'pending',first_seen,succeeded_at,succeeded_at,succeeded_at,'historical'
FROM (
    SELECT DISTINCT ON (i.original_id) i.original_id,v.payload,s.succeeded_at,
        min(s.succeeded_at) OVER (PARTITION BY i.original_id) AS first_seen
    FROM public.contestkorea_daily_items i JOIN public.contestkorea_daily_snapshots s USING (collection_date)
    JOIN public.contestkorea_item_versions v USING (content_hash)
    ORDER BY i.original_id,i.collection_date DESC
) latest;

-- Compact eligible-only catalog. Identical payloads are shared across dates.
CREATE TABLE public.contestkorea_collection_runs (
    id uuid PRIMARY KEY,
    run_order bigint GENERATED ALWAYS AS IDENTITY,
    collection_date date NOT NULL,
    mode text NOT NULL CHECK (mode IN ('scheduled', 'manual')),
    status text NOT NULL CHECK (status IN ('running', 'success', 'failed', 'already_running', 'already_succeeded')),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    collected_count integer CHECK (collected_count >= 0),
    error_code text,
    CHECK ((status = 'running') = (finished_at IS NULL)),
    CHECK (status <> 'success' OR collected_count IS NOT NULL)
);
CREATE INDEX contestkorea_runs_day ON public.contestkorea_collection_runs (collection_date, mode, status);
CREATE INDEX contestkorea_runs_order ON public.contestkorea_collection_runs (run_order DESC);
CREATE TABLE public.contestkorea_daily_snapshots (
    collection_date date PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES public.contestkorea_collection_runs(id),
    succeeded_at timestamptz NOT NULL,
    collected_count integer NOT NULL CHECK (collected_count >= 0)
);
CREATE TABLE public.contestkorea_item_versions (
    content_hash bytea PRIMARY KEY CHECK (octet_length(content_hash) = 32),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);
CREATE TABLE public.contestkorea_daily_items (
    collection_date date NOT NULL REFERENCES public.contestkorea_daily_snapshots(collection_date),
    original_id text NOT NULL,
    content_hash bytea NOT NULL REFERENCES public.contestkorea_item_versions(content_hash),
    PRIMARY KEY (collection_date, original_id)
);
CREATE INDEX contestkorea_items_version ON public.contestkorea_daily_items (content_hash);
ALTER TABLE public.contestkorea_collection_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contestkorea_daily_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contestkorea_item_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contestkorea_daily_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.contestkorea_collection_runs, public.contestkorea_daily_snapshots,
    public.contestkorea_item_versions, public.contestkorea_daily_items FROM PUBLIC, anon, authenticated;

-- Server-only catalog; no student/authenticated Data API access.
CREATE TABLE public.dacon_collection_runs (
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
CREATE INDEX dacon_runs_date_status ON public.dacon_collection_runs (collection_date, mode, status);
CREATE INDEX dacon_runs_started ON public.dacon_collection_runs (run_order DESC);

CREATE TABLE public.dacon_daily_snapshots (
    collection_date date PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES public.dacon_collection_runs(id),
    succeeded_at timestamptz NOT NULL,
    collected_count integer NOT NULL CHECK (collected_count >= 0)
);
CREATE TABLE public.dacon_daily_items (
    collection_date date NOT NULL REFERENCES public.dacon_daily_snapshots(collection_date),
    source text NOT NULL CHECK (source IN ('dacon', 'daker')),
    original_id text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (collection_date, source, original_id)
);
ALTER TABLE public.dacon_collection_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dacon_daily_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dacon_daily_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.dacon_collection_runs, public.dacon_daily_snapshots, public.dacon_daily_items FROM PUBLIC, anon, authenticated;
-- The backend's existing postgres connection owns these tables. No public policies.

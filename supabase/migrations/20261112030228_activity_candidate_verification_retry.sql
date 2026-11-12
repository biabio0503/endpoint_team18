-- Never-verified discoveries have no successful observation to timestamp.
-- Existing candidates, successful clocks, daily snapshots and RLS stay intact.
ALTER TABLE public.activity_candidates ALTER COLUMN last_success_at DROP NOT NULL;
CREATE INDEX activity_candidates_unverified_retry
    ON public.activity_candidates(source,next_check_at)
    WHERE last_success_at IS NULL;

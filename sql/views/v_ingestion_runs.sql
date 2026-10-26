-- v_ingestion_runs
--
-- The run log (ingestion_runs) as the dashboards may see it: one row per
-- ingestion run per source, for the Ingestion health dashboard's "runs by
-- status" card. v_ingestion_daily only carries run and ok-run counts.
--
-- Deliberately OMITS ingestion_runs.params and .error: errors are redacted
-- (src/utils/redaction.py) but still operational detail, and the Ingestion
-- health dashboard is public. Read the error text with SQL as the owner.
--
--   status   running | ok | partial | failed | skipped_budget
--            (a `running` row with no finished_at = a killed process)
--   snapshot_date is the run's UTC start date, the date its snapshots land on.
--   calls_made counts every HTTP attempt, retries included (the number the
--   monthly Adzuna budget bills against, src/ingestion/budget.py).
--
-- Rows exist only from when the run log was added; earlier days show up in
-- v_ingestion_daily (built on job_snapshots) with zero runs.

CREATE OR REPLACE VIEW v_ingestion_runs AS
SELECT
    r.id            AS run_id,
    r.source,
    r.snapshot_date,
    r.status,
    r.started_at,
    r.finished_at,
    r.calls_made,
    r.pages_fetched,
    r.jobs_processed,
    r.jobs_new
FROM ingestion_runs r;

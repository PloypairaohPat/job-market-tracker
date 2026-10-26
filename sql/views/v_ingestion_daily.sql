-- v_ingestion_daily
--
-- The ingestion clock, one row per (UTC snapshot_date, source): is data
-- actually arriving every day? Read by `python -m src.pipeline.health`'s
-- volume check and, later, the data-quality dashboard.
--
-- Built on job_snapshots (joined to jobs for the source: job_snapshots has
-- no source column), NOT on ingestion_runs, so days from before the run log
-- existed still show up. A day with no snapshot for a source has no row --
-- a missed day is a gap in this view, never a zero row.
--
--   snapshot_rows      job_snapshots rows that day (one per job per day, so
--                      equal to distinct_jobs by construction; both kept so
--                      a future schema change that breaks that is visible)
--   distinct_jobs      distinct jobs observed that day
--   new_jobs           jobs whose first_seen_at falls on that UTC date
--   n_runs, n_ok_runs  ingestion_runs rows for that snapshot_date (0 before
--                      the run log existed)
--   calls_made,
--   jobs_processed     summed over those runs; NULL when no run row exists
--                      (unknown, not zero -- the call was made, just not logged)
--
-- snapshot_date is a UTC date (ingest_page uses datetime.now(UTC).date()),
-- so a run near UTC midnight can land on either side of it. See
-- docs/daily-operation.md for why the scheduled task runs at 07:15 local.

CREATE OR REPLACE VIEW v_ingestion_daily AS
WITH snap AS (
    SELECT s.snapshot_date, j.source,
           COUNT(*)                  AS snapshot_rows,
           COUNT(DISTINCT s.job_id)  AS distinct_jobs
    FROM job_snapshots s
    JOIN jobs j ON j.id = s.job_id
    GROUP BY s.snapshot_date, j.source
),
first_seen AS (
    SELECT (j.first_seen_at AT TIME ZONE 'UTC')::date AS snapshot_date, j.source,
           COUNT(*) AS new_jobs
    FROM jobs j
    GROUP BY 1, 2
),
runs AS (
    SELECT r.snapshot_date, r.source,
           COUNT(*)                                  AS n_runs,
           COUNT(*) FILTER (WHERE r.status = 'ok')   AS n_ok_runs,
           SUM(r.calls_made)                         AS calls_made,
           SUM(r.jobs_processed)                     AS jobs_processed
    FROM ingestion_runs r
    GROUP BY r.snapshot_date, r.source
)
SELECT
    snap.snapshot_date,
    snap.source,
    snap.snapshot_rows,
    snap.distinct_jobs,
    COALESCE(fs.new_jobs, 0)   AS new_jobs,
    COALESCE(runs.n_runs, 0)   AS n_runs,
    COALESCE(runs.n_ok_runs, 0) AS n_ok_runs,
    runs.calls_made,
    runs.jobs_processed
FROM snap
LEFT JOIN first_seen fs
       ON fs.snapshot_date = snap.snapshot_date AND fs.source = snap.source
LEFT JOIN runs
       ON runs.snapshot_date = snap.snapshot_date AND runs.source = snap.source;

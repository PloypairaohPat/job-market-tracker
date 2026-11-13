-- v_job_observation_spans
--
-- One row per job in the ANALYSIS POPULATION that has at least one snapshot:
-- when it was first and last returned by its source's daily search, and two
-- honesty flags saying whether those edges are exact or fall in a gap.
--
-- "Seen" means "returned inside that day's search window", NOT "live on the
-- employer's site". A job can leave the window while still posted (see
-- v_search_window_coverage for each query's captured share), and a missed
-- day (no snapshot for the source) hides whatever happened that day. So a
-- span is an observation span, never a posting lifetime, unless both
-- flags say the edges are exact.
--
-- Population (same as v_market_jobs): commercial = source 'adzuna';
-- federal = source 'usajobs' AND in_scope.
--
-- A source's snapshot days are the UTC dates on which ANY of that source's
-- jobs has a job_snapshots row (the days its search ran and stored results).
--
-- Columns:
--   job_id, market, source
--   first_seen_date      first snapshot_date for the job
--   last_seen_date       last snapshot_date for the job
--   days_seen            snapshot rows for the job
--   source_days_in_span  the source's snapshot days from first to last seen,
--                        inclusive. days_seen < source_days_in_span means
--                        the job dropped out of the window and came back
--   entry_is_exact       true when the source has a snapshot on the day
--                        before first_seen_date: the job really appeared
--                        that day, not during a missed day or before the
--                        series began
--   exit_state           'still_listed': seen on the source's latest
--                          snapshot day
--                        'exit_exact': the source has a snapshot the day
--                          after last_seen_date and the job isn't in it
--                        'exit_in_gap': the day after last_seen_date has no
--                          snapshot for the source, so the exit day is unknown

CREATE OR REPLACE VIEW v_job_observation_spans AS
WITH pop AS (
    SELECT ap.job_id, j.source, ap.market
    FROM v_analysis_population ap
    JOIN jobs j ON j.id = ap.job_id
),
source_days AS (
    SELECT DISTINCT j.source, s.snapshot_date
    FROM job_snapshots s
    JOIN jobs j ON j.id = s.job_id
),
source_latest AS (
    SELECT source, MAX(snapshot_date) AS latest_date
    FROM source_days
    GROUP BY source
),
spans AS (
    SELECT p.job_id, p.market, p.source,
           MIN(s.snapshot_date) AS first_seen_date,
           MAX(s.snapshot_date) AS last_seen_date,
           COUNT(*)             AS days_seen
    FROM pop p
    JOIN job_snapshots s ON s.job_id = p.job_id
    GROUP BY p.job_id, p.market, p.source
)
SELECT
    sp.job_id,
    sp.market,
    sp.source,
    sp.first_seen_date,
    sp.last_seen_date,
    sp.days_seen,
    (SELECT COUNT(*) FROM source_days d
      WHERE d.source = sp.source
        AND d.snapshot_date BETWEEN sp.first_seen_date AND sp.last_seen_date
    ) AS source_days_in_span,
    EXISTS (
        SELECT 1 FROM source_days d
        WHERE d.source = sp.source AND d.snapshot_date = sp.first_seen_date - 1
    ) AS entry_is_exact,
    CASE
        WHEN sp.last_seen_date = sl.latest_date THEN 'still_listed'
        WHEN EXISTS (
            SELECT 1 FROM source_days d
            WHERE d.source = sp.source AND d.snapshot_date = sp.last_seen_date + 1
        ) THEN 'exit_exact'
        ELSE 'exit_in_gap'
    END AS exit_state
FROM spans sp
JOIN source_latest sl ON sl.source = sp.source;

-- v_daily_market_flow
--
-- One row per (market, snapshot day of the market's source): how many
-- analysis-population jobs the day's search returned, how many were seen
-- for the first time, and how many for the last time.
--
-- "Seen" means "returned inside that day's search window", NOT "live". A job
-- that leaves the window still exists; a day after a missed day absorbs
-- that day's arrivals; and the first day of the series counts every job as
-- first seen. Read each row with v_search_window_coverage (how much of each
-- query the window captured that day) and prev_day_has_snapshot.
--
-- Population (same as v_market_jobs): commercial = source 'adzuna';
-- federal = source 'usajobs' AND in_scope. A source's snapshot days are the
-- UTC dates on which any of its jobs has a job_snapshots row, so a day the
-- source ran but returned no in-scope job is a row with zeros, and a day it
-- didn't run has no row.
--
-- Columns:
--   market, snapshot_date
--   jobs_seen               population jobs with a snapshot that day
--   jobs_first_seen         ... whose first snapshot is that day
--   jobs_last_seen          ... whose last snapshot is that day; NULL on the
--                           source's latest snapshot day (not known yet)
--   prev_day_has_snapshot   the source has a snapshot on the calendar day
--                           before. When false, jobs_first_seen includes
--                           arrivals from the missed day(s) (or, on the
--                           first day, everything already listed)

CREATE OR REPLACE VIEW v_daily_market_flow AS
WITH pop AS (
    SELECT ap.job_id, j.source, ap.market
    FROM v_analysis_population ap
    JOIN jobs j ON j.id = ap.job_id
),
markets AS (
    SELECT * FROM (VALUES ('commercial', 'adzuna'), ('federal', 'usajobs')) AS m(market, source)
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
    SELECT p.job_id, p.market,
           MIN(s.snapshot_date) AS first_seen_date,
           MAX(s.snapshot_date) AS last_seen_date
    FROM pop p
    JOIN job_snapshots s ON s.job_id = p.job_id
    GROUP BY p.job_id, p.market
),
seen AS (
    SELECT p.market, s.snapshot_date, COUNT(*) AS jobs_seen
    FROM pop p
    JOIN job_snapshots s ON s.job_id = p.job_id
    GROUP BY p.market, s.snapshot_date
),
firsts AS (
    SELECT market, first_seen_date AS snapshot_date, COUNT(*) AS n
    FROM spans GROUP BY market, first_seen_date
),
lasts AS (
    SELECT market, last_seen_date AS snapshot_date, COUNT(*) AS n
    FROM spans GROUP BY market, last_seen_date
)
SELECT
    m.market,
    d.snapshot_date,
    COALESCE(se.jobs_seen, 0) AS jobs_seen,
    COALESCE(f.n, 0)          AS jobs_first_seen,
    CASE WHEN d.snapshot_date = sl.latest_date THEN NULL
         ELSE COALESCE(l.n, 0) END AS jobs_last_seen,
    EXISTS (
        SELECT 1 FROM source_days p
        WHERE p.source = d.source AND p.snapshot_date = d.snapshot_date - 1
    ) AS prev_day_has_snapshot
FROM markets m
JOIN source_days d   ON d.source = m.source
JOIN source_latest sl ON sl.source = m.source
LEFT JOIN seen se    ON se.market = m.market AND se.snapshot_date = d.snapshot_date
LEFT JOIN firsts f   ON f.market = m.market AND f.snapshot_date = d.snapshot_date
LEFT JOIN lasts l    ON l.market = m.market AND l.snapshot_date = d.snapshot_date;

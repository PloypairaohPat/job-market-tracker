-- Data window for Transparency: snapshot dates covered and jobs per market.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily)       AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily)       AS last_snapshot,
    MAX(n_jobs) FILTER (WHERE market = 'commercial')         AS n_commercial_jobs,
    MAX(n_jobs) FILTER (WHERE market = 'federal')            AS n_federal_jobs
FROM v_field_completeness;

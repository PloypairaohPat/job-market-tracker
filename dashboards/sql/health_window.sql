-- Data window for Ingestion health: snapshot dates covered and jobs first seen in them.
SELECT
    MIN(snapshot_date)            AS first_snapshot,
    MAX(snapshot_date)            AS last_snapshot,
    COUNT(DISTINCT snapshot_date) AS n_snapshot_days,
    SUM(new_jobs)                 AS n_jobs
FROM v_ingestion_daily;

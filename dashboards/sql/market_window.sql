-- Data window for Market overview: snapshot dates covered and jobs in the analysis population.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily) AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily) AS last_snapshot,
    COUNT(*)                                           AS n_jobs
FROM v_market_jobs;
